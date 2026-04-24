// apps/browser/src/lib/tracer-renderer.ts
/**
 * Shared tracer line renderer used by both clip review (TrajectoryEditor)
 * and video export (video-frame-pipeline-v4).
 *
 * Ensures what users see during review is identical to the exported video.
 */

import { TracerStyle } from '../types/tracer'

export interface TrajectoryPointInput {
  timestamp: number
  x: number  // normalized 0-1
  y: number  // normalized 0-1
  confidence?: number
  interpolated?: boolean
}

export interface ContentBounds {
  offsetX: number
  offsetY: number
  width: number
  height: number
}

export interface DrawTracerLineOptions {
  ctx: CanvasRenderingContext2D
  points: TrajectoryPointInput[]
  currentTime: number     // blob-relative current time
  width: number           // canvas pixel width
  height: number          // canvas pixel height
  style: TracerStyle
  /** Optional content bounds for letterboxing (defaults to full canvas) */
  contentBounds?: ContentBounds
}

export interface DrawTracerLineResult {
  /** Animation progress 0-1 (0 = not started, 1 = complete) */
  progress: number
}

/**
 * Convert time ratio (0-1) to display progress using golf ball physics.
 *
 * Ball launches at ~160mph, lands at ~70mph. Covers most distance early,
 * slows near apex, descends at near-constant speed.
 *
 * Uses easeOutCubic/linear blend for smooth, monotonic curve.
 * Exported for testing.
 */
export function timeToProgress(t: number): number {
  if (t <= 0) return 0
  if (t >= 1) return 1

  // easeOutCubic: fast start, slowing down
  const easeOut = 1 - Math.pow(1 - t, 3)

  // Linear component
  const linear = t

  // Blend from easeOut (early) toward more linear (late)
  // Goes from 0.7 at t=0 to 0.3 at t=1
  const easeWeight = 0.7 - 0.4 * t

  // Combined progress (weighted average of two monotonic curves)
  const progress = easeOut * easeWeight + linear * (1 - easeWeight)

  return Math.min(1, Math.max(0, progress))
}

/**
 * Draw the tracer line on a canvas context.
 *
 * Handles: physics-based easing, path-length interpolation, 3-layer bezier
 * glow rendering. Returns progress so callers can manage completion hold etc.
 */
export function drawTracerLine(options: DrawTracerLineOptions): DrawTracerLineResult {
  const { ctx, points, currentTime, width, height, style, contentBounds } = options

  if (points.length < 2) return { progress: 0 }

  const firstTime = points[0].timestamp
  const lastTime = points[points.length - 1].timestamp
  const timeRange = lastTime - firstTime

  // Calculate time ratio (0-1 through the trajectory)
  const timeRatio = timeRange > 0
    ? Math.max(0, Math.min(1, (currentTime - firstTime) / timeRange))
    : 0

  if (timeRatio <= 0) return { progress: 0 }

  // Apply physics easing
  const displayProgress = timeToProgress(timeRatio)

  // Pre-calculate cumulative path lengths (normalized 0-1 coords)
  const pathLengths: number[] = [0]
  for (let i = 1; i < points.length; i++) {
    const dx = points[i].x - points[i - 1].x
    const dy = points[i].y - points[i - 1].y
    pathLengths.push(pathLengths[i - 1] + Math.sqrt(dx * dx + dy * dy))
  }
  const totalPathLength = pathLengths[pathLengths.length - 1]
  const targetDistance = displayProgress * totalPathLength

  // Find interpolation point along path
  let endPointIndex = points.length - 1
  let interpolatedEnd: { x: number; y: number } | null = null

  for (let i = 1; i < points.length; i++) {
    if (pathLengths[i] >= targetDistance) {
      endPointIndex = i
      const segStart = pathLengths[i - 1]
      const segLen = pathLengths[i] - segStart
      const t = segLen > 0 ? (targetDistance - segStart) / segLen : 0
      interpolatedEnd = {
        x: points[i - 1].x + t * (points[i].x - points[i - 1].x),
        y: points[i - 1].y + t * (points[i].y - points[i - 1].y),
      }
      break
    }
  }

  // Build visible points with interpolated end
  const visible = points.slice(0, endPointIndex)
  if (interpolatedEnd) {
    visible.push({
      ...points[Math.min(endPointIndex, points.length - 1)],
      x: interpolatedEnd.x,
      y: interpolatedEnd.y,
    })
  }

  if (visible.length < 2) return { progress: displayProgress }

  // Coordinate transform: normalized (0-1) → canvas pixels
  const bounds = contentBounds || { offsetX: 0, offsetY: 0, width, height }
  const toPixel = (nx: number, ny: number) => ({
    x: bounds.offsetX + Math.max(0, Math.min(1, nx)) * bounds.width,
    y: bounds.offsetY + Math.max(0, Math.min(1, ny)) * bounds.height,
  })

  // Draw smooth curve path using quadratic Bezier splines
  const tracePath = () => {
    const first = toPixel(visible[0].x, visible[0].y)
    ctx.moveTo(first.x, first.y)

    if (visible.length === 2) {
      const second = toPixel(visible[1].x, visible[1].y)
      ctx.lineTo(second.x, second.y)
      return
    }

    for (let i = 1; i < visible.length - 1; i++) {
      const cur = toPixel(visible[i].x, visible[i].y)
      const next = toPixel(visible[i + 1].x, visible[i + 1].y)
      ctx.quadraticCurveTo(cur.x, cur.y, (cur.x + next.x) / 2, (cur.y + next.y) / 2)
    }

    const last = toPixel(visible[visible.length - 1].x, visible[visible.length - 1].y)
    const secondLast = toPixel(visible[visible.length - 2].x, visible[visible.length - 2].y)
    ctx.quadraticCurveTo(secondLast.x, secondLast.y, last.x, last.y)
  }

  ctx.save()

  // Layer 1: Outer glow
  ctx.strokeStyle = style.glowColor || style.color
  ctx.lineWidth = (style.lineWidth || 3) + (style.glowRadius || 8)
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.shadowColor = style.glowColor || style.color
  ctx.shadowBlur = 16
  ctx.globalAlpha = 0.4
  ctx.beginPath()
  tracePath()
  ctx.stroke()

  // Layer 2: Inner glow
  ctx.shadowBlur = 8
  ctx.lineWidth = (style.lineWidth || 3) + 2
  ctx.globalAlpha = 0.6
  ctx.beginPath()
  tracePath()
  ctx.stroke()

  // Layer 3: Core line
  ctx.strokeStyle = style.color || '#ff0000'
  ctx.shadowBlur = 4
  ctx.lineWidth = style.lineWidth || 3
  ctx.globalAlpha = 1.0
  ctx.beginPath()
  tracePath()
  ctx.stroke()

  ctx.restore()

  return { progress: displayProgress }
}
