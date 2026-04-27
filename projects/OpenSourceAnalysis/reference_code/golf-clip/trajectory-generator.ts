// apps/browser/src/lib/trajectory-generator.ts
/**
 * Trajectory generation utilities for golf ball flight paths.
 *
 * Generates bezier curve trajectories based on landing point, shot configuration,
 * and optional origin/apex markers.
 */

import { TrajectoryData, TrajectoryPoint, TracerConfig } from '../stores/processingStore'

/** 2D point with normalized coordinates (0-1) */
export interface Point2D {
  x: number
  y: number
}

/** Shot shape lateral curve offsets */
const SHAPE_CURVE_OFFSETS: Record<TracerConfig['shape'], number> = {
  hook: -0.15,
  draw: -0.08,
  straight: 0,
  fade: 0.08,
  slice: 0.15,
}

/** Shot height arc multipliers */
const HEIGHT_MULTIPLIERS: Record<TracerConfig['height'], number> = {
  low: 0.15,
  medium: 0.25,
  high: 0.35,
}

/** Default golfer origin position (bottom center of frame) */
const DEFAULT_ORIGIN: Point2D = { x: 0.5, y: 0.85 }

/** Target trajectory points per second for smooth animation */
const TRAJECTORY_POINTS_PER_SECOND = 60

/**
 * Generate a trajectory curve from landing point and configuration.
 *
 * Uses a quadratic bezier curve where the control point is calculated
 * such that the curve passes through the apex at t=0.5.
 *
 * For a quadratic bezier B(t) = (1-t)²P0 + 2(1-t)tP1 + t²P2
 * At t=0.5: B(0.5) = 0.25*P0 + 0.5*P1 + 0.25*P2
 * Solving for P1 to make B(0.5) = apex:
 * P1 = 2*apex - 0.5*(P0 + P2)
 *
 * @param landingPoint - Where the ball lands (normalized 0-1 coordinates)
 * @param config - Tracer configuration (height, shape, flightTime)
 * @param originPoint - Optional origin point (defaults to bottom center)
 * @param apexPoint - Optional apex point (auto-calculated if not provided)
 * @param startTimeOffset - When trajectory starts relative to video timeline
 * @returns TrajectoryData with sampled points along the curve
 *
 * @example
 * ```ts
 * const trajectory = generateTrajectory(
 *   { x: 0.8, y: 0.3 },
 *   { height: 'high', shape: 'fade', flightTime: 3.5 },
 *   undefined, // use default origin
 *   undefined, // auto-calculate apex
 *   1.5 // trajectory starts 1.5s into video
 * )
 * ```
 */
export function generateTrajectory(
  landingPoint: Point2D,
  config: TracerConfig,
  originPoint?: Point2D,
  apexPoint?: Point2D,
  startTimeOffset: number = 0
): TrajectoryData {
  const origin = originPoint || DEFAULT_ORIGIN

  // Calculate apex based on config if not provided
  const heightMultiplier = HEIGHT_MULTIPLIERS[config.height]
  const defaultApex: Point2D = {
    x: (origin.x + landingPoint.x) / 2,
    y: Math.min(origin.y, landingPoint.y) - heightMultiplier,
  }
  const apex = apexPoint || defaultApex

  // When user specifies apex, disable shape curve offset (they picked exact position)
  // Shape curve only applies to auto-calculated apex
  const shapeCurve = apexPoint ? 0 : SHAPE_CURVE_OFFSETS[config.shape]

  // Calculate the control point that makes the bezier pass THROUGH the apex at t=0.5
  const controlPoint: Point2D = {
    x: 2 * apex.x - 0.5 * origin.x - 0.5 * landingPoint.x,
    y: 2 * apex.y - 0.5 * origin.y - 0.5 * landingPoint.y,
  }

  // Generate points along quadratic bezier
  // Use 60 points per second for smooth animation at 60fps
  const numPoints = Math.max(30, Math.ceil(config.flightTime * TRAJECTORY_POINTS_PER_SECOND))
  const points: TrajectoryPoint[] = []

  for (let i = 0; i <= numPoints; i++) {
    const t = i / numPoints
    const timestamp = startTimeOffset + t * config.flightTime

    // Quadratic bezier: B(t) = (1-t)²P0 + 2(1-t)tP1 + t²P2
    const mt = 1 - t
    const x = mt * mt * origin.x + 2 * mt * t * (controlPoint.x + shapeCurve * t) + t * t * landingPoint.x
    const y = mt * mt * origin.y + 2 * mt * t * controlPoint.y + t * t * landingPoint.y

    points.push({
      timestamp,
      x: Math.max(0, Math.min(1, x)),
      y: Math.max(0, Math.min(1, y)),
      confidence: 1.0,
      interpolated: false,
    })
  }

  return {
    shot_id: 'generated',
    points,
    confidence: 1.0,
    apex_point: {
      ...points[Math.floor(numPoints / 2)],
      x: Math.max(0, Math.min(1, apex.x)),
      y: Math.max(0, Math.min(1, apex.y)),
    },
    frame_width: 1920,
    frame_height: 1080,
  }
}
