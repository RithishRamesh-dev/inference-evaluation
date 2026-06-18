import { useState, useEffect, useRef } from 'react'
import { api } from '../api'
import type { Dataset, DatasetItem } from '../types'

export default function Datasets() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [selected, setSelected] = useState<Dataset | null>(null)
  const [items, setItems] = useState<DatasetItem[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [newType, setNewType] = useState('qa')
  const [creating, setCreating] = useState(false)
  const [newQ, setNewQ] = useState('')
  const [newA, setNewA] = useState('')
  const [addingItem, setAddingItem] = useState(false)
  const [showBulk, setShowBulk] = useState(false)
  const [bulkText, setBulkText] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const loadDatasets = () => api.datasets.list().then(setDatasets)

  useEffect(() => { loadDatasets() }, [])

  const selectDataset = (d: Dataset) => {
    setSelected(d)
    api.datasets.items(d.id).then(setItems)
  }

  const createDataset = async () => {
    if (!newName.trim()) return
    setCreating(true)
    try {
      await api.datasets.create({ name: newName, description: newDesc, task_type: newType })
      setNewName(''); setNewDesc(''); setShowCreate(false)
      loadDatasets()
    } finally { setCreating(false) }
  }

  const deleteDataset = async (id: string) => {
    if (!confirm('Delete this dataset and all its items?')) return
    await api.datasets.delete(id)
    if (selected?.id === id) { setSelected(null); setItems([]) }
    loadDatasets()
  }

  const addItem = async () => {
    if (!selected || !newQ.trim()) return
    setAddingItem(true)
    try {
      await api.datasets.addItem(selected.id, { question: newQ, expected_answer: newA })
      setNewQ(''); setNewA('')
      api.datasets.items(selected.id).then(setItems)
      loadDatasets()
    } finally { setAddingItem(false) }
  }

  const importBulk = async () => {
    if (!selected || !bulkText.trim()) return
    const lines = bulkText.trim().split('\n')
    for (const line of lines) {
      const [q, a] = line.split('\t')
      if (q?.trim()) await api.datasets.addItem(selected.id, { question: q.trim(), expected_answer: (a || '').trim() })
    }
    setBulkText(''); setShowBulk(false)
    api.datasets.items(selected.id).then(setItems)
    loadDatasets()
  }

  const uploadFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!selected || !e.target.files?.length) return
    const file = e.target.files[0]
    const formData = new FormData()
    formData.append('file', file)
    await fetch(`/api/datasets/${selected.id}/import`, {
      method: 'POST',
      headers: { 'X-API-Key': import.meta.env.VITE_API_KEY || '' },
      body: formData,
    })
    api.datasets.items(selected.id).then(setItems)
    loadDatasets()
  }

  return (
    <div className="flex h-full">
      {/* Left: dataset list */}
      <div className="w-64 border-r border-do-grey-200 flex flex-col shrink-0">
        <div className="p-4 border-b border-do-grey-200">
          <div className="flex items-center justify-between mb-0.5">
            <h1 className="text-sm font-bold text-gray-800">Custom Datasets</h1>
            <button onClick={() => setShowCreate(true)} className="text-xs text-do-blue hover:underline">＋ New</button>
          </div>
          <p className="text-xs text-gray-500">Upload or build test sets for evaluations</p>
        </div>
        <div className="flex-1 overflow-y-auto">
          {datasets.length === 0 && (
            <p className="text-xs text-gray-600 px-4 py-3">No datasets yet</p>
          )}
          {datasets.map(d => (
            <button key={d.id} onClick={() => selectDataset(d)}
              className={`w-full text-left px-4 py-3 border-b border-do-grey-200 hover:bg-do-grey-100 ${selected?.id === d.id ? 'bg-do-grey-100' : ''}`}>
              <p className="text-sm text-gray-700 truncate">{d.name}</p>
              <p className="text-xs text-gray-600 mt-0.5">{d.item_count} items · {d.task_type}</p>
            </button>
          ))}
        </div>
        {showCreate && (
          <div className="p-3 border-t border-do-grey-200 space-y-2">
            <input className="input text-xs" placeholder="Dataset name" value={newName} onChange={e => setNewName(e.target.value)} />
            <input className="input text-xs" placeholder="Description" value={newDesc} onChange={e => setNewDesc(e.target.value)} />
            <select className="input text-xs" value={newType} onChange={e => setNewType(e.target.value)}>
              <option value="qa">QA</option>
              <option value="classification">Classification</option>
              <option value="generation">Generation</option>
              <option value="code">Code</option>
            </select>
            <div className="flex gap-1">
              <button onClick={createDataset} disabled={creating} className="btn-primary text-xs py-1 flex-1">{creating ? 'Creating…' : 'Create'}</button>
              <button onClick={() => setShowCreate(false)} className="btn-secondary text-xs py-1">Cancel</button>
            </div>
          </div>
        )}
      </div>

      {/* Right: items */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {!selected && (
          <div className="flex items-center justify-center h-full text-gray-600 text-sm">
            Select a dataset to view items
          </div>
        )}
        {selected && (
          <>
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold text-gray-800">{selected.name}</h2>
                <p className="text-xs text-gray-600">{selected.description || 'No description'} · {items.length} items</p>
              </div>
              <div className="flex gap-2">
                <a href={api.datasets.exportUrl(selected.id, 'csv')} className="btn-secondary text-xs py-1">⬇ CSV</a>
                <a href={api.datasets.exportUrl(selected.id, 'json')} className="btn-secondary text-xs py-1">⬇ JSON</a>
                <input type="file" ref={fileRef} accept=".csv,.json" className="hidden" onChange={uploadFile} />
                <button onClick={() => fileRef.current?.click()} className="btn-secondary text-xs py-1">⬆ Import</button>
                <button onClick={() => deleteDataset(selected.id)} className="text-xs text-red-500 hover:text-red-400 px-2">Delete</button>
              </div>
            </div>

            {/* Add item */}
            <div className="card space-y-2">
              <p className="text-xs font-semibold text-gray-600">Add Item</p>
              <textarea className="input text-xs resize-none" rows={2} placeholder="Question / prompt"
                value={newQ} onChange={e => setNewQ(e.target.value)} />
              <textarea className="input text-xs resize-none" rows={2} placeholder="Expected answer (optional)"
                value={newA} onChange={e => setNewA(e.target.value)} />
              <div className="flex gap-2">
                <button onClick={addItem} disabled={addingItem || !newQ.trim()} className="btn-primary text-xs py-1">
                  {addingItem ? 'Adding…' : '＋ Add'}
                </button>
                <button onClick={() => setShowBulk(p => !p)} className="btn-secondary text-xs py-1">
                  Bulk (Tab-separated)
                </button>
              </div>
              {showBulk && (
                <div className="space-y-2">
                  <textarea className="input text-xs font-mono resize-none" rows={5}
                    placeholder={"question\tanswer\nquestion2\tanswer2"}
                    value={bulkText} onChange={e => setBulkText(e.target.value)} />
                  <button onClick={importBulk} className="btn-primary text-xs py-1">Import Lines</button>
                </div>
              )}
            </div>

            {/* Items list */}
            <div className="space-y-2">
              {items.map(item => (
                <div key={item.id} className="card text-xs space-y-1">
                  <div className="flex items-start gap-2">
                    <div className="flex-1">
                      <p className="text-gray-700 font-medium">{item.question}</p>
                      {item.expected_answer && <p className="text-gray-600 mt-0.5">→ {item.expected_answer}</p>}
                    </div>
                    <button onClick={() => {
                      api.datasets.deleteItem(selected.id, item.id).then(() => {
                        setItems(p => p.filter(i => i.id !== item.id))
                        loadDatasets()
                      })
                    }} className="text-gray-700 hover:text-red-400 shrink-0">✕</button>
                  </div>
                  <span className="text-gray-700">{item.source}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
