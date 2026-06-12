import { useState, useEffect } from 'react'
import { api } from '../api'
import type { RunNote } from '../types'

const TYPE_OPTIONS = ['general', 'finding', 'recommendation', 'issue']
const TYPE_COLOR: Record<string, string> = {
  finding: 'badge-blue',
  recommendation: 'badge-green',
  issue: 'badge-red',
  general: 'badge-gray',
}

interface Props { runId: number }

export default function NotesPanel({ runId }: Props) {
  const [notes, setNotes] = useState<RunNote[]>([])
  const [content, setContent] = useState('')
  const [noteType, setNoteType] = useState('general')
  const [isPinned, setIsPinned] = useState(false)
  const [editing, setEditing] = useState<number | null>(null)
  const [editContent, setEditContent] = useState('')
  const [loading, setLoading] = useState(false)

  const refresh = () => {
    api.notes.list(runId).then(setNotes)
  }

  useEffect(() => { refresh() }, [runId])

  const addNote = async () => {
    if (!content.trim()) return
    setLoading(true)
    try {
      await api.notes.create(runId, { content, note_type: noteType, is_pinned: isPinned })
      setContent('')
      setIsPinned(false)
      refresh()
    } finally {
      setLoading(false)
    }
  }

  const saveEdit = async (noteId: number) => {
    await api.notes.update(runId, noteId, { content: editContent })
    setEditing(null)
    refresh()
  }

  const togglePin = async (note: RunNote) => {
    await api.notes.update(runId, note.id, { is_pinned: !note.is_pinned })
    refresh()
  }

  const deleteNote = async (noteId: number) => {
    if (!confirm('Delete this note?')) return
    await api.notes.delete(runId, noteId)
    refresh()
  }

  return (
    <div>
      {/* Add form */}
      <div className="mb-4">
        <textarea
          className="input text-sm resize-none h-20"
          placeholder="Add a note, finding, or recommendation…"
          value={content}
          onChange={e => setContent(e.target.value)}
        />
        <div className="flex items-center gap-2 mt-2">
          <select
            className="input w-auto text-xs py-1"
            value={noteType}
            onChange={e => setNoteType(e.target.value)}
          >
            {TYPE_OPTIONS.map(t => <option key={t}>{t}</option>)}
          </select>
          <label className="flex items-center gap-1 text-xs text-gray-400 cursor-pointer">
            <input type="checkbox" checked={isPinned} onChange={e => setIsPinned(e.target.checked)} />
            Pin
          </label>
          <button
            className="btn-primary text-xs py-1.5 ml-auto"
            onClick={addNote}
            disabled={loading || !content.trim()}
          >
            Add Note
          </button>
        </div>
      </div>

      {/* Notes list */}
      <div className="space-y-2">
        {notes.length === 0 && (
          <p className="text-sm text-gray-600 text-center py-4">No notes yet.</p>
        )}
        {notes.map(note => (
          <div key={note.id} className={`bg-gray-800/50 border rounded-lg p-3 ${note.is_pinned ? 'border-yellow-800/60' : 'border-gray-700'}`}>
            {editing === note.id ? (
              <div>
                <textarea
                  className="input text-sm resize-none h-20 w-full"
                  value={editContent}
                  onChange={e => setEditContent(e.target.value)}
                />
                <div className="flex gap-2 mt-2">
                  <button className="btn-primary text-xs py-1" onClick={() => saveEdit(note.id)}>Save</button>
                  <button className="btn-secondary text-xs py-1" onClick={() => setEditing(null)}>Cancel</button>
                </div>
              </div>
            ) : (
              <>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className={TYPE_COLOR[note.note_type] ?? 'badge-gray'}>{note.note_type}</span>
                    {note.is_pinned && <span className="text-yellow-500 text-xs">📌</span>}
                    <span className="text-xs text-gray-600">{new Date(note.created_at).toLocaleDateString()}</span>
                  </div>
                  <div className="flex gap-1 shrink-0">
                    <button className="text-gray-600 hover:text-yellow-400 text-xs" onClick={() => togglePin(note)}>
                      {note.is_pinned ? '📌' : '📍'}
                    </button>
                    <button className="text-gray-600 hover:text-gray-300 text-xs" onClick={() => { setEditing(note.id); setEditContent(note.content) }}>
                      ✏️
                    </button>
                    <button className="text-gray-600 hover:text-red-400 text-xs" onClick={() => deleteNote(note.id)}>
                      🗑
                    </button>
                  </div>
                </div>
                <p className="text-sm text-gray-300 mt-1.5 whitespace-pre-wrap">{note.content}</p>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
