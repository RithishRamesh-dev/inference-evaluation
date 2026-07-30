"""Inference-engine adapters for model deployments (Benchmarking Evaluation — Step 2).

The deployment feature is engine-agnostic: the ONLY engine-specific surface is
producing the launch spec — docker image, serve command/args, and health path.
Everything else (SSH deploy/poll, logs, health, the deployments collection,
routers, SSE, and the Step-3 benchmark layer that hits the OpenAI-compatible
`localhost:<port>/v1`) is shared.

Each engine implements `EngineAdapter` and registers itself in `ENGINES`. Adding
a new engine = one new adapter, no other code changes.

v1 ships **vLLM** with rich recipes from recipes.vllm.ai. **SGLang** is a
registered placeholder (`available=False`) so the seam exists; it has no
structured recipe feed (prose-only cookbook), so it's deferred.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ── Shared docker-run helpers (engine-neutral pieces) ─────────────────────────

def _device_flags(platform: str | None) -> list[str]:
    """GPU passthrough flags differ by vendor: NVIDIA uses --gpus all; AMD ROCm
    exposes /dev/kfd + /dev/dri. Vendor comes from the droplet, not a guess."""
    if (platform or "").upper() == "AMD":
        return ["--device", "/dev/kfd", "--device", "/dev/dri",
                "--group-add", "video", "--security-opt", "seccomp=unconfined"]
    return ["--gpus", "all"]


def _docker_run_prefix(container: str, port: int, env: dict[str, str], platform: str | None) -> list[str]:
    """Common `docker run` flags shared by every engine."""
    argv = ["docker", "run", "-d", "--name", container]
    argv += _device_flags(platform)
    argv += ["--privileged", "--ipc=host", "--shm-size", "16g", "--restart", "unless-stopped"]
    argv += ["-p", f"{port}:{port}"]
    argv += ["-v", "/root/.cache/huggingface:/root/.cache/huggingface"]
    for k, v in (env or {}).items():
        if k:
            argv += ["-e", f"{k}={v}"]
    return argv


def image_gpu_mismatch(image: str | None, platform: str | None) -> str | None:
    """Return a user-facing error if a container image can't run on the droplet's
    GPU platform, else None.

    Catches the common, cryptic case: the NVIDIA/CUDA build of vLLM
    ('vllm/vllm-openai') scheduled onto an AMD ROCm GPU. That image has no CUDA
    runtime on AMD, so vLLM dies at startup with 'Failed to infer device type'
    after a few restarts. Happens whenever a model's vLLM recipe has no ROCm
    variant — resolve_recipe then falls back to the CUDA recommended image.

    ROCm images (e.g. 'rocm/vllm', 'vllm/vllm-openai-rocm') are explicitly allowed:
    the CUDA image name is a prefix of the ROCm one, so 'rocm' must exempt it."""
    img = (image or "").lower()
    is_rocm = "rocm" in img
    if (platform or "").upper() == "AMD" and "vllm/vllm-openai" in img and not is_rocm:
        return (f"This is an AMD (ROCm) GPU, but '{image}' is the NVIDIA/CUDA build of vLLM, "
                "which can't run on AMD hardware (it fails at startup with 'Failed to infer "
                "device type'). This model has no ROCm recipe variant for this GPU — deploy it "
                "on an NVIDIA GPU, or set a ROCm image (e.g. 'rocm/vllm') and redeploy.")
    return None


def hf_model_is_gated(model_id: str) -> bool:
    """Whether a HuggingFace repo needs auth to download (gated/private). Probes
    the public config.json: 401/403 => gated, 200 => open. No hardcoded list.
    Unknown/errors => False (don't block; the deploy surfaces a clear error)."""
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as c:
            r = c.get(f"https://huggingface.co/{model_id}/resolve/main/config.json")
        return r.status_code in (401, 403)
    except Exception:
        return False


def _argv_to_args(tokens: list[str]) -> list[dict]:
    """Turn a flat token list (`--flag value --bare`) into ordered
    [{flag, value}] pairs for the editable UI grid. Bare flags get value=''."""
    args: list[dict] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.startswith("-"):
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                args.append({"flag": t, "value": tokens[i + 1]}); i += 2
            else:
                args.append({"flag": t, "value": ""}); i += 1
        else:
            i += 1  # stray positional (e.g. the model id) — skip
    return args


def _args_to_tokens(args: list[dict]) -> list[str]:
    out: list[str] = []
    for a in args or []:
        flag = (a.get("flag") or "").strip()
        if not flag:
            continue
        out.append(flag)
        val = a.get("value")
        if val not in (None, ""):
            out.append(str(val))
    return out


# ── Adapter interface ─────────────────────────────────────────────────────────

class EngineAdapter:
    name: str = ""
    display_name: str = ""
    available: bool = False
    health_path: str = "/health"
    default_port: int = 8000

    def list_models(self) -> list[dict]:
        """Catalog for the model picker: [{hf_id, title, provider}]."""
        raise NotImplementedError

    def resolve_recipe(self, model_id: str, gpu: dict) -> dict:
        """Resolve the default launch spec for `model_id` on this droplet's GPU.
        Returns a dict the UI seeds its editable form from."""
        raise NotImplementedError

    def build_run_argv(self, container: str, model_ref: str, image: str,
                       args: list[dict], env: dict, port: int, platform: str | None) -> list[str]:
        """Full `docker run` argv to serve the model. Engine-specific because the
        container command shape differs (vLLM: positional model; SGLang: flags)."""
        raise NotImplementedError


# ── vLLM ───────────────────────────────────────────────────────────────────────

class VllmEngine(EngineAdapter):
    name = "vllm"
    display_name = "vLLM"
    available = True
    health_path = "/health"
    default_port = 8000
    BASE = "https://recipes.vllm.ai"

    # Map a DigitalOcean GPU to a recipes.vllm.ai hardware key. Prefer an exact
    # model match; if the model string is sparse/unrecognized, fall back to the
    # vendor and pick the first matching variant the recipe actually offers — so
    # an AMD droplet still gets a ROCm variant (not the CUDA recommended_command)
    # even when DO's gpu model name doesn't contain the chip name.
    def _hw_key(self, gpu: dict, by_hw: dict | None = None) -> str | None:
        by_hw = by_hw or {}
        blob = (gpu.get("gpu_model") or "").lower().replace(" ", "").replace("-", "").replace("_", "")
        for k in ("mi300x", "mi325x", "mi355x", "gb200", "gb300", "b200", "b300", "h200", "h100"):
            if k in blob:
                return k
        platform = (gpu.get("gpu_platform") or "").upper()
        if platform == "AMD":
            for k in ("mi300x", "mi325x", "mi355x"):
                if k in by_hw:
                    return k
        return None  # NVIDIA L40S / RTX / A100 etc. → recommended_command (CUDA) is correct

    def list_models(self) -> list[dict]:
        with httpx.Client(timeout=20) as c:
            r = c.get(f"{self.BASE}/models.json")
            r.raise_for_status()
            out = []
            for m in r.json():
                hf = m.get("hf_id")
                if hf:
                    out.append({"hf_id": hf, "title": m.get("title") or hf,
                                "provider": m.get("provider") or ""})
            return out

    def resolve_recipe(self, model_id: str, gpu: dict) -> dict:
        with httpx.Client(timeout=20, follow_redirects=True) as c:
            r = c.get(f"{self.BASE}/{model_id}.json")
            r.raise_for_status()
            recipe = r.json()

            rec = recipe.get("recommended_command") or {}
            by_hw = rec.get("by_hardware") or {}
            hw_key = self._hw_key(gpu, by_hw)
            if hw_key and hw_key in by_hw:
                try:
                    hr = c.get(f"{self.BASE}{by_hw[hw_key]}")
                    hr.raise_for_status()
                    rec = hr.json()
                except Exception:
                    logger.warning("vLLM hw variant %s fetch failed; using recommended", hw_key)
                    hw_key = None
            else:
                hw_key = None

        model = recipe.get("model") or {}
        model_ref = model.get("model_id") or model_id
        image = rec.get("docker_image") or model.get("docker_image") or "vllm/vllm-openai:latest"

        argv = rec.get("argv") or []
        if len(argv) >= 3 and argv[0] == "vllm" and argv[1] == "serve":
            arg_tokens = argv[3:]
        else:
            arg_tokens = [t for t in argv if t not in ("vllm", "serve", model_ref)]
        args = _argv_to_args(arg_tokens)

        # Tensor-parallel size = the droplet's GPU count (per the recipe's own note).
        pflag = (rec.get("strategy_spec") or {}).get("parallel_flag")
        count = gpu.get("gpu_count")
        if pflag and count:
            existing = next((a for a in args if a["flag"] == pflag), None)
            if existing:
                existing["value"] = str(count)
            else:
                args.append({"flag": pflag, "value": str(count)})

        env = {**(model.get("base_env") or {}), **(rec.get("env") or {})}

        opt_in = set(recipe.get("opt_in_features") or [])
        features = []
        for fname, f in (recipe.get("features") or {}).items():
            features.append({
                "name": fname,
                "description": (f or {}).get("description") or "",
                "args": (f or {}).get("args") or [],
                "enabled": fname not in opt_in,
            })

        return {
            "engine": self.name,
            "model_id": model_ref,
            "docker_image": image,
            "server_args": args,
            "env": env,
            "port": self.default_port,
            "features": features,
            "hardware_key": hw_key,
            "recipe_source_url": f"{self.BASE}/{model_id}.json",
            "context_length": model.get("context_length"),
            "min_vllm_version": model.get("min_vllm_version"),
            "gated": hf_model_is_gated(model_ref),
        }

    def build_run_argv(self, container, model_ref, image, args, env, port, platform):
        # Force the vLLM CLI as the entrypoint and pass `serve` explicitly, so the
        # container always runs `vllm serve <model> <args>` regardless of the image's
        # own entrypoint. vllm/vllm-openai already entrypoints to `vllm serve` (so
        # this is equivalent), while images with a bare `vllm` entrypoint (e.g.
        # rocm/vllm) would otherwise never receive `serve` and fail at startup.
        argv = _docker_run_prefix(container, port, env, platform)
        argv += ["--entrypoint", "vllm", image, "serve", model_ref]
        argv += _args_to_tokens(args)
        flags = {(a.get("flag") or "") for a in (args or [])}
        if "--host" not in flags:
            argv += ["--host", "0.0.0.0"]
        if "--port" not in flags:
            argv += ["--port", str(port)]
        return argv


# ── SGLang ───────────────────────────────────────────────────────────────────

class SglangEngine(EngineAdapter):
    name = "sglang"
    display_name = "SGLang"
    available = True
    health_path = "/health"      # OpenAI-compatible API is served at /v1
    default_port = 30000

    # SGLang has no structured recipe feed (unlike recipes.vllm.ai). The model
    # picker reuses the same engine-agnostic HF catalog vLLM uses — it's just
    # {hf_id, title, provider} metadata for models people benchmark, and SGLang
    # serves those same HF models. Anything not listed is still deployable via the
    # deploy form's paste box.
    CATALOG_URL = "https://recipes.vllm.ai/models.json"

    # NVIDIA has a stable moving tag. ROCm images are version+chip pinned with no
    # 'latest', so we resolve the newest matching tag live from Docker Hub
    # (_rocm_image) rather than rot a hardcoded version.
    NV_IMAGE = "lmsysorg/sglang:latest"
    ROCM_REPO = "lmsysorg/sglang"
    # Used ONLY if the live tag lookup fails (network / rate-limit) — not the normal
    # path. The live lookup supersedes it; bump occasionally as a safety net.
    ROCM_FALLBACK = {
        "mi30x": "lmsysorg/sglang:v0.5.16-rocm700-mi30x",
        "mi35x": "lmsysorg/sglang:v0.5.16-rocm700-mi35x",
    }

    def list_models(self) -> list[dict]:
        with httpx.Client(timeout=20) as c:
            r = c.get(self.CATALOG_URL)
            r.raise_for_status()
            out = []
            for m in r.json():
                hf = m.get("hf_id")
                if hf:
                    out.append({"hf_id": hf, "title": m.get("title") or hf,
                                "provider": m.get("provider") or ""})
            return out

    def _chip_family(self, gpu: dict) -> str | None:
        """SGLang ROCm images are split by chip family: mi30x covers MI300X/MI325X,
        mi35x covers MI350X/MI355X."""
        blob = (gpu.get("gpu_model") or "").lower().replace(" ", "").replace("-", "")
        if any(k in blob for k in ("mi300x", "mi325x")):
            return "mi30x"
        if any(k in blob for k in ("mi350x", "mi355x")):
            return "mi35x"
        return None

    def _rocm_image(self, family: str) -> str:
        """Newest SGLang ROCm image for a chip family, resolved live from Docker Hub
        so a pinned version can't rot. Tags look like 'v0.5.16-rocm700-mi30x'; we pick
        the highest (sglang_version, rocm_version). Falls back to a known-good pin only
        if the lookup fails or nothing matches."""
        pat = re.compile(rf"^v(\d+(?:\.\d+)+(?:\.post\d+)?)-rocm(\d+)-{family}$")
        best: tuple[tuple, str] | None = None   # ((version, rocm), tag)
        try:
            url = f"https://hub.docker.com/v2/repositories/{self.ROCM_REPO}/tags"
            params: dict = {"page_size": 100, "ordering": "last_updated"}
            with httpx.Client(timeout=15) as c:
                for _ in range(3):   # newest are first; a few pages is plenty
                    r = c.get(url, params=params)
                    r.raise_for_status()
                    data = r.json()
                    for t in data.get("results", []):
                        m = pat.match(t.get("name", ""))
                        if not m:
                            continue
                        ver = tuple(int(x) for x in re.findall(r"\d+", m.group(1)))
                        key = (ver, int(m.group(2)))
                        if best is None or key > best[0]:
                            best = (key, f"{self.ROCM_REPO}:{t['name']}")
                    url = data.get("next") or ""
                    params = {}
                    if not url:
                        break
        except Exception:
            logger.warning("SGLang ROCm tag lookup failed; using fallback", exc_info=True)
        return best[1] if best else self.ROCM_FALLBACK[family]

    def resolve_recipe(self, model_id: str, gpu: dict) -> dict:
        platform = (gpu.get("gpu_platform") or "").upper()
        family = self._chip_family(gpu)
        if platform == "AMD":
            image = self._rocm_image(family) if family else self.ROCM_FALLBACK["mi30x"]
        else:
            image = self.NV_IMAGE

        # No recipe feed to draw from — seed only the tensor-parallel size (per the
        # droplet's GPU count). Everything else (context length, quantization, memory
        # fraction, …) is left for the user to tune in the editable arg grid.
        args: list[dict] = []
        count = gpu.get("gpu_count")
        if count and count > 1:
            args.append({"flag": "--tp", "value": str(count)})

        return {
            "engine": self.name,
            "model_id": model_id,
            "docker_image": image,
            "server_args": args,
            "env": {},
            "port": self.default_port,
            "features": [],
            "hardware_key": family,
            "recipe_source_url": "https://docs.sglang.io/docs/advanced_features/server_arguments",
            "context_length": None,
            "min_vllm_version": None,
            "gated": hf_model_is_gated(model_id),
        }

    def build_run_argv(self, container, model_ref, image, args, env, port, platform):
        # Force `python3 -m sglang.launch_server` as the command regardless of the
        # image's own entrypoint (mirrors the vLLM adapter's forced entrypoint). The
        # model is passed via --model-path (SGLang takes no positional model).
        argv = _docker_run_prefix(container, port, env, platform)
        argv += ["--entrypoint", "python3", image,
                 "-m", "sglang.launch_server", "--model-path", model_ref]
        argv += _args_to_tokens(args)
        flags = {(a.get("flag") or "") for a in (args or [])}
        if "--host" not in flags:
            argv += ["--host", "0.0.0.0"]
        if "--port" not in flags:
            argv += ["--port", str(port)]
        return argv


ENGINES: dict[str, EngineAdapter] = {
    e.name: e for e in (VllmEngine(), SglangEngine())
}


def get_engine(name: str) -> EngineAdapter:
    eng = ENGINES.get((name or "").lower())
    if not eng:
        raise ValueError(f"Unknown inference engine: {name!r}")
    return eng


def engine_list() -> list[dict]:
    return [{"name": e.name, "display_name": e.display_name, "available": e.available}
            for e in ENGINES.values()]
