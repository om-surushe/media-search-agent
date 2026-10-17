import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MediaCard } from './MediaCard'

// Mock react-router-dom navigate (used by FaceStrip internally)
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))

const baseProps = {
  id: 'abc123',
  onClick: vi.fn(),
}

describe('MediaCard', () => {
  describe('thumbnail', () => {
    it('renders an img with src derived from media_id (not path)', () => {
      const { container } = render(<MediaCard {...baseProps} path="/mnt/p/Photos/IMG_001.heic" />)
      const img = container.querySelector('img')
      expect(img).not.toBeNull()
      // Thumbnail is keyed by id (media_id), not the file path — avoids stem collisions
      expect(img).toHaveAttribute('src', '/thumbnails/abc123.jpg')
    })

    it('renders no img when id is null', () => {
      const { container } = render(<MediaCard {...baseProps} id={null} />)
      expect(container.querySelector('img')).toBeNull()
    })

    it('renders no img when id is empty string', () => {
      const { container } = render(<MediaCard {...baseProps} id="" />)
      expect(container.querySelector('img')).toBeNull()
    })
  })

  describe('video badge', () => {
    it('shows a clear video indicator for video type', () => {
      render(<MediaCard {...baseProps} type="video" />)
      expect(screen.getByText('VIDEO')).toBeInTheDocument()
    })

    it('shows formatted duration when video has duration', () => {
      render(<MediaCard {...baseProps} type="video" duration={125} />)
      expect(screen.getByText('· 02:05')).toBeInTheDocument()
    })

    it('formats long durations with hours', () => {
      render(<MediaCard {...baseProps} type="video" duration={3665} />)
      expect(screen.getByText('· 1:01:05')).toBeInTheDocument()
    })

    it('does not show video metadata for image type', () => {
      render(<MediaCard {...baseProps} type="image" duration={125} sceneMatches={[{ keyframe_id: 1, timestamp: 65, caption_excerpt: 'a scene' }]} />)
      expect(screen.queryByText('VIDEO')).toBeNull()
      expect(screen.queryByText('· 01:05')).toBeNull()
      expect(screen.queryByText('a scene')).toBeNull()
    })
  })

  describe('matching scene context', () => {
    it('shows matching timestamp and the stored scene description', () => {
      render(<MediaCard {...baseProps} type="video" sceneMatches={[{ keyframe_id: 1, timestamp: 65, caption_excerpt: 'a person entering the room' }]} />)
      expect(screen.getByTitle('01:05 · a person entering the room')).toBeInTheDocument()
      expect(screen.getByText('01:05 ·')).toBeInTheDocument()
      expect(screen.getByText(/a person entering the room/)).toBeInTheDocument()
    })
  })

  describe('interaction', () => {
    it('calls onClick when clicked', async () => {
      const onClick = vi.fn()
      render(<MediaCard {...baseProps} onClick={onClick} />)
      await userEvent.click(screen.getByRole('button'))
      expect(onClick).toHaveBeenCalledOnce()
    })
  })
})
