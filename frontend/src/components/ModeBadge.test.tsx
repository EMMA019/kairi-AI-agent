import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { ModeBadge } from './ModeBadge'

describe('ModeBadge', () => {
  it('renders chat mode', () => {
    render(<ModeBadge mode="chat" status="idle" onToggle={() => {}} />)
    expect(screen.getByText('Chat')).toBeInTheDocument()
  })
})
