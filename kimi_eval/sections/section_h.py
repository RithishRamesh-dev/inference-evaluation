"""Section H — Accuracy Smoke Tests  (ACC-001 to ACC-006)
Full benchmark requires dataset files (future stage).
These representative problems confirm the model is in the correct ballpark.
"""
from core.common import console, record, req, body


def run():
    console.rule("[bold cyan]H — Accuracy (Smoke Tests)[/]")
    console.print("  [dim]Full benchmark (OCRBench/AIME/MMMU) requires dataset files — future stage.[/dim]\n")

    tests = [
        # (prompt, expected_in_answer, req_id, think, temp)
        ("How many ways can 5 distinct books be arranged on a shelf? Integer answer only.",
         "120", "ACC-002", True, 1.0),
        ("How many ways can 5 distinct books be arranged on a shelf? Integer answer only.",
         "120", "ACC-005", False, 0.6),
        ("What is 1+2+3+...+10? Integer answer only.",
         "55", "ACC-002b", True, 1.0),
        ("Invoice #7823 — Total: $4,250. What is the invoice number? Number only.",
         "7823", "ACC-004", False, 0.6),
        ("Invoice #7823 — Total: $4,250. What is the invoice number? Number only.",
         "7823", "ACC-001", True, 1.0),
        ("A car travels 60 km in 1.5 hours. Average speed in km/h? Number only.",
         "40", "ACC-003", True, 1.0),
        ("A car travels 60 km in 1.5 hours. Average speed in km/h? Number only.",
         "40", "ACC-006", False, 0.6),
    ]

    for prompt, answer, req_id, think, temp in tests:
        mode = "think" if think else "non-think"
        data, _, _, err = req(prompt, think=think, temperature=temp, max_tokens=512)
        if err or not data:
            record("H", f"{req_id} ({mode})", False, f"err={err}")
        else:
            resp    = body(data)
            correct = answer in resp
            record("H", f"{req_id} ({mode}) answer={answer}",
                   correct, f"correct={correct} | resp={resp[:80]!r}")

    console.print(
        "\n  [yellow]NOTE:[/] Official targets: OCRBench 91%/92%, "
        "AIME 98.4%/70.5%, MMMU Pro 78.8%/74.9%.\n"
        "  Validate against full datasets in future stage."
    )
