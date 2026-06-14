"""Custom dataset management routes."""
from __future__ import annotations
import csv
import json
import io
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from pymongo.database import Database
from database import get_db, _id as doc_id, oid
from schemas import DatasetCreate, DatasetOut, DatasetItemCreate, DatasetItemOut

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def _dataset_out(doc: dict, db: Database) -> DatasetOut:
    d = doc_id(doc)
    d["item_count"] = db.custom_dataset_items.count_documents({"dataset_id": d["id"]})
    return DatasetOut(**d)


@router.get("", response_model=list[DatasetOut])
def list_datasets(db: Database = Depends(get_db)):
    docs = list(db.custom_datasets.find({}).sort("created_at", -1))
    return [_dataset_out(d, db) for d in docs]


@router.post("", response_model=DatasetOut, status_code=201)
def create_dataset(body: DatasetCreate, db: Database = Depends(get_db)):
    now = datetime.now(timezone.utc)
    doc = {**body.model_dump(), "created_at": now, "updated_at": now}
    result = db.custom_datasets.insert_one(doc)
    return _dataset_out(db.custom_datasets.find_one({"_id": result.inserted_id}), db)


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: str, db: Database = Depends(get_db)):
    doc = db.custom_datasets.find_one({"_id": oid(dataset_id)})
    if not doc:
        raise HTTPException(404, "Dataset not found")
    return _dataset_out(doc, db)


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: str, db: Database = Depends(get_db)):
    db.custom_datasets.delete_one({"_id": oid(dataset_id)})
    db.custom_dataset_items.delete_many({"dataset_id": dataset_id})


@router.get("/{dataset_id}/items", response_model=list[DatasetItemOut])
def list_items(dataset_id: str, limit: int = Query(100, le=500), offset: int = 0, db: Database = Depends(get_db)):
    docs = list(db.custom_dataset_items.find({"dataset_id": dataset_id}).skip(offset).limit(limit))
    return [DatasetItemOut(**doc_id(d)) for d in docs]


@router.post("/{dataset_id}/items", response_model=DatasetItemOut, status_code=201)
def create_item(dataset_id: str, body: DatasetItemCreate, db: Database = Depends(get_db)):
    if not db.custom_datasets.find_one({"_id": oid(dataset_id)}):
        raise HTTPException(404, "Dataset not found")
    now = datetime.now(timezone.utc)
    doc = {"dataset_id": dataset_id, **body.model_dump(), "created_at": now}
    result = db.custom_dataset_items.insert_one(doc)
    return DatasetItemOut(**doc_id(db.custom_dataset_items.find_one({"_id": result.inserted_id})))


@router.delete("/{dataset_id}/items/{item_id}", status_code=204)
def delete_item(dataset_id: str, item_id: str, db: Database = Depends(get_db)):
    db.custom_dataset_items.delete_one({"_id": oid(item_id), "dataset_id": dataset_id})


@router.post("/{dataset_id}/import")
async def import_items(dataset_id: str, file: UploadFile = File(...), db: Database = Depends(get_db)):
    if not db.custom_datasets.find_one({"_id": oid(dataset_id)}):
        raise HTTPException(404, "Dataset not found")
    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    items = []
    if file.filename and file.filename.endswith(".json"):
        data = json.loads(text)
        if isinstance(data, list):
            items = [{"question": str(d.get("question", "")), "expected_answer": str(d.get("expected_answer", d.get("answer", ""))), "context": d.get("context"), "metadata": {}, "source": "import"} for d in data]
    else:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            items.append({"question": row.get("question", ""), "expected_answer": row.get("expected_answer", ""), "context": row.get("context"), "metadata": {}, "source": "import"})

    if not items:
        raise HTTPException(400, "No valid items found")
    now = datetime.now(timezone.utc)
    docs = [{"dataset_id": dataset_id, "created_at": now, **item} for item in items]
    db.custom_dataset_items.insert_many(docs)
    return {"imported": len(docs)}


@router.get("/{dataset_id}/export")
def export_dataset(dataset_id: str, format: str = Query("json"), db: Database = Depends(get_db)):
    if not db.custom_datasets.find_one({"_id": oid(dataset_id)}):
        raise HTTPException(404, "Dataset not found")
    items = list(db.custom_dataset_items.find({"dataset_id": dataset_id}))
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["question", "expected_answer", "context"])
        for item in items:
            writer.writerow([item.get("question", ""), item.get("expected_answer", ""), item.get("context", "")])
        return StreamingResponse(io.BytesIO(output.getvalue().encode()), media_type="text/csv",
                                 headers={"Content-Disposition": f"attachment; filename=dataset_{dataset_id}.csv"})
    data = [{"question": d.get("question", ""), "expected_answer": d.get("expected_answer", ""), "context": d.get("context")} for d in items]
    return data
