import { useState } from 'react'
import { InlineLoading } from './InlineLoading'

interface ChatBoxProps {
  onFeedback: (text: string) => Promise<void>
  onRegen: () => Promise<void>
  onSkip: () => Promise<void>
  busy?: boolean
}

export function ChatBox({ onFeedback, onRegen, onSkip, busy }: ChatBoxProps) {
  const [text, setText] = useState('')

  const submit = async () => {
    if (!text.trim()) return
    const value = text
    setText('')
    await onFeedback(value)
  }

  return (
    <div className="chat-box">
      <textarea
        rows={3}
        placeholder="Type feedback to refine (e.g. 'make bullet 3 more concise')..."
        value={text}
        disabled={busy}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit()
        }}
      />
      <div className="chat-actions">
        <button className="primary" disabled={busy || !text.trim()} onClick={submit}>Send feedback</button>
        <button disabled={busy} onClick={onRegen}>Regenerate</button>
        <button disabled={busy} onClick={onSkip}>Use original / Skip</button>
      </div>
      {busy && <InlineLoading text="waiting on Claude" />}
    </div>
  )
}
