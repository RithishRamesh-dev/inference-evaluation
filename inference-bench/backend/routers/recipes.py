"""Recipe routes (Benchmarking Evaluation — Step 2).

Live-fetches the engine's model catalog and per-model launch recipe, resolved
against a specific droplet's GPU. Nothing here is hardcoded — vLLM data comes
from recipes.vllm.ai. The result seeds the editable deploy form.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.database import Database

from database import get_db, oid
import engines

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


@router.get("/engines")
def list_engines():
    """Inference engines and whether each is available in this build."""
    return engines.engine_list()


@router.get("/models")
def list_models(engine: str = "vllm"):
    """Catalog for the model picker: [{hf_id, title, provider}]."""
    try:
        eng = engines.get_engine(engine)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not eng.available:
        raise HTTPException(400, f"{eng.display_name} deployments are not available yet")
    try:
        return eng.list_models()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Could not reach the {eng.display_name} recipe catalog: {e}")


@router.get("/resolve")
def resolve_recipe(
    model: str,
    droplet_id: str,
    engine: str = "vllm",
    db: Database = Depends(get_db),
):
    """Resolve the default launch spec for `model` on `droplet_id`'s GPU."""
    try:
        eng = engines.get_engine(engine)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not eng.available:
        raise HTTPException(400, f"{eng.display_name} deployments are not available yet")

    droplet = db.gpu_droplets.find_one({"_id": oid(droplet_id)})
    if not droplet:
        raise HTTPException(404, "Droplet not found")
    gpu = {
        "gpu_model": droplet.get("gpu_model"),
        "gpu_count": droplet.get("gpu_count"),
        "gpu_platform": droplet.get("gpu_platform"),
        "gpu_vram_gb": droplet.get("gpu_vram_gb"),
    }
    try:
        return eng.resolve_recipe(model, gpu)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(404, f"No {eng.display_name} recipe found for '{model}'")
        raise HTTPException(502, f"Recipe fetch failed: {e}")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Could not reach the recipe catalog: {e}")
    except NotImplementedError as e:
        raise HTTPException(400, str(e))
