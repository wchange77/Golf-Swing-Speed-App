/**
 * Audio strike detection using Essentia.js
 *
 * Detects golf ball strikes in audio using onset detection and spectral analysis.
 * Essentia.js is a WebAssembly port of the Essentia audio analysis library.
 *
 * IMPORTANT: This module requires audio at 44100Hz sample rate.
 * Essentia.js SuperFluxExtractor does not work correctly with lower sample rates.
 */

import { createLogger } from './logger'

const log = createLogger('AudioDetector')

// Essentia types (library doesn't have proper TS types for all exports)
interface EssentiaModule {
  arrayToVector(array: Float32Array): unknown
  vectorToArray(vector: unknown): Float32Array
  SuperFluxExtractor(
    signal: unknown,
    combine?: number,
    frameSize?: number,
    hopSize?: number,
    ratioThreshold?: number,
    sampleRate?: number,
    threshold?: number
  ): { onsets: unknown }
  SpectralCentroidTime(array: unknown, sampleRate?: number): { centroid: number }
  Flatness(array: unknown): { flatness: number }
  BandPass(
    signal: unknown,
    bandwidth?: number,
    cutoffFrequency?: number,
    sampleRate?: number
  ): { signal: unknown }
  RMS(array: unknown): { rms: number }
}

let essentia: EssentiaModule | null = null
let loaded = false

export interface StrikeDetection {
  timestamp: number
  confidence: number
  spectralCentroid: number
  spectralFlatness: number
  onsetStrength: number
  decayRatio: number // Ratio of energy decay: lower = sharper transient (real ball strike), higher = slower decay (practice swing)
}

export interface DetectionConfig {
  frequencyLow: number       // Hz - lower bound of bandpass
  frequencyHigh: number      // Hz - upper bound of bandpass
  minStrikeInterval: number  // Seconds between strikes
  sensitivity: number        // 0-1, higher = more detections
}

export const DEFAULT_CONFIG: DetectionConfig = {
  frequencyLow: 1000,
  frequencyHigh: 8000,
  minStrikeInterval: 25.0, // 25 seconds minimum between strikes (golf swing interval)
  sensitivity: 0.5,
}

/**
 * Load Essentia WebAssembly module
 * Must be called before using detectStrikes()
 */
export async function loadEssentia(): Promise<void> {
  if (loaded) return

  // Dynamic import of Essentia.js modules
  // Using ES modules - EssentiaWASM is a named export (not default) and is the module itself (not a factory)
  // See: https://mtg.github.io/essentia.js/docs/api/tutorial-1.%20Getting%20started.html
  const [{ EssentiaWASM }, { default: Essentia }] = await Promise.all([
    import('essentia.js/dist/essentia-wasm.es.js'),
    import('essentia.js/dist/essentia.js-core.es.js'),
  ])

  // EssentiaWASM is the WASM module object directly (not a factory function)
  essentia = new Essentia(EssentiaWASM) as EssentiaModule

  loaded = true
}

/**
 * Check if Essentia is loaded and ready
 */
export function isEssentiaLoaded(): boolean {
  return loaded
}

/**
 * Unload Essentia module for cleanup
 */
export function unloadEssentia(): void {
  essentia = null
  loaded = false
}

/**
 * Detect golf ball strikes in audio data
 *
 * Uses SuperFluxExtractor for onset detection (optimized for percussive sounds)
 * and spectral analysis to filter for strike-like sounds.
 *
 * IMPORTANT: Audio must be at 44100Hz sample rate for Essentia.js to work correctly.
 *
 * @param audioData - Float32Array of audio samples (-1.0 to 1.0)
 * @param sampleRate - Sample rate of the audio (must be 44100 Hz)
 * @param config - Optional detection configuration
 * @returns Array of detected strikes with timestamps and confidence scores
 */
export async function detectStrikes(
  audioData: Float32Array,
  sampleRate: number,
  config: Partial<DetectionConfig> = {}
): Promise<StrikeDetection[]> {
  // Validation
  if (audioData.length === 0) {
    throw new Error('Audio data cannot be empty')
  }
  if (sampleRate <= 0) {
    throw new Error('Sample rate must be positive')
  }
  if (sampleRate !== 44100) {
    log.warn('Non-standard sample rate. Essentia.js works best with 44100Hz.', { sampleRate })
  }
  if (!essentia || !loaded) {
    throw new Error('Essentia not loaded. Call loadEssentia() first.')
  }

  const cfg = { ...DEFAULT_CONFIG, ...config }

  // Convert to Essentia vector
  const audioVector = essentia.arrayToVector(audioData)

  // Apply bandpass filter to isolate strike frequencies
  // Golf ball strikes have significant energy in 1000-8000 Hz range
  const bandwidth = cfg.frequencyHigh - cfg.frequencyLow
  const centerFrequency = (cfg.frequencyLow + cfg.frequencyHigh) / 2

  const filtered = essentia.BandPass(
    audioVector,
    bandwidth,
    centerFrequency,
    sampleRate
  )

  // Use SuperFluxExtractor for onset detection
  // This algorithm is optimized for percussive transients
  const frameSize = 2048
  const hopSize = 256

  // Adjust threshold based on sensitivity (lower threshold = more detections)
  const threshold = 0.1 - cfg.sensitivity * 0.08 // Range: 0.02 to 0.10

  // Call SuperFluxExtractor with filtered signal
  const onsetResult = essentia.SuperFluxExtractor(
    filtered.signal,
    20,            // combine: 20ms double onset threshold
    frameSize,
    hopSize,
    16,            // ratioThreshold (default)
    sampleRate,
    threshold
  )

  // SuperFluxExtractor returns onsets as an Essentia vector, convert to array
  // Note: vectorToArray throws "Empty vector input" if the vector is empty,
  // so we need to catch that case and return an empty array instead
  let onsetTimes: number[] = []
  if (onsetResult.onsets) {
    try {
      const converted = essentia.vectorToArray(onsetResult.onsets)
      onsetTimes = Array.from(converted)
    } catch (e) {
      // Empty vector - no onsets detected, which is a valid result
      log.debug('Empty onset vector', { error: String(e) })
      onsetTimes = []
    }
  }

  // Filter by minimum interval and calculate confidence for each onset
  const strikes: StrikeDetection[] = []
  let lastOnsetTime = -Infinity

  for (const onsetTime of onsetTimes) {
    // Enforce minimum interval between strikes
    if (onsetTime - lastOnsetTime < cfg.minStrikeInterval) {
      continue
    }

    // Extract window around onset for spectral analysis
    const windowSamples = Math.floor(frameSize / 2)
    const onsetSample = Math.floor(onsetTime * sampleRate)
    const windowStart = Math.max(0, onsetSample - windowSamples)
    const windowEnd = Math.min(audioData.length, onsetSample + windowSamples)

    if (windowEnd - windowStart < 100) {
      continue // Skip if window too small
    }

    const window = audioData.slice(windowStart, windowEnd)

    // Skip if window is too small for spectral analysis
    if (window.length < 256) {
      continue
    }

    const windowVector = essentia.arrayToVector(window)

    // Calculate spectral features with error handling
    // Some Essentia algorithms can fail on edge cases
    let centroid = 3500, flatness = 0.3, rms = 0.1 // defaults
    try {
      const centroidResult = essentia.SpectralCentroidTime(windowVector, sampleRate)
      centroid = centroidResult.centroid
    } catch (e) {
      log.debug('SpectralCentroidTime failed, using default', { error: String(e) })
    }
    try {
      const flatnessResult = essentia.Flatness(windowVector)
      flatness = flatnessResult.flatness
    } catch (e) {
      log.debug('Flatness calculation failed, using default', { error: String(e) })
    }
    try {
      const rmsResult = essentia.RMS(windowVector)
      rms = rmsResult.rms
    } catch (e) {
      log.debug('RMS calculation failed, using default', { error: String(e) })
    }

    // Calculate decay ratio: compare energy after onset to peak energy
    // Lower decay ratio = faster decay = sharper transient = more likely real ball strike
    // Higher decay ratio = slower decay = whoosh sound = more likely practice swing
    const decayRatio = calculateDecayRatio(audioData, onsetSample, sampleRate, essentia)

    // Calculate confidence score based on spectral features and decay ratio
    const confidence = calculateConfidence(centroid, flatness, rms, decayRatio)

    // Only include detections above minimum confidence
    if (confidence > 0.3) {
      strikes.push({
        timestamp: onsetTime,
        confidence,
        spectralCentroid: centroid,
        spectralFlatness: flatness,
        onsetStrength: rms,
        decayRatio,
      })
      lastOnsetTime = onsetTime
    }
  }

  return strikes
}

/**
 * Calculate decay ratio: ratio of energy after onset to peak energy
 *
 * Real ball strikes have fast decay (sharp transient) -> low decay ratio
 * Practice swings have slower decay (whoosh sound) -> high decay ratio
 *
 * @param audioData - Full audio buffer
 * @param onsetSample - Sample index of the onset
 * @param sampleRate - Audio sample rate
 * @param essentia - Essentia module for RMS calculation
 * @returns Decay ratio between 0 and 1 (lower = sharper transient)
 */
function calculateDecayRatio(
  audioData: Float32Array,
  onsetSample: number,
  sampleRate: number,
  essentia: EssentiaModule
): number {
  // Measure energy in a window around the onset (peak window: 0-25ms after onset)
  const peakWindowMs = 25
  const peakWindowSamples = Math.floor((peakWindowMs / 1000) * sampleRate)

  // Measure energy in a decay window (50-100ms after onset)
  const decayStartMs = 50
  const decayEndMs = 100
  const decayStartSamples = Math.floor((decayStartMs / 1000) * sampleRate)
  const decayEndSamples = Math.floor((decayEndMs / 1000) * sampleRate)

  // Extract peak window
  const peakStart = onsetSample
  const peakEnd = Math.min(audioData.length, onsetSample + peakWindowSamples)

  // Extract decay window
  const decayStart = Math.min(audioData.length, onsetSample + decayStartSamples)
  const decayEnd = Math.min(audioData.length, onsetSample + decayEndSamples)

  // Need sufficient samples for both windows
  if (peakEnd - peakStart < 100 || decayEnd - decayStart < 100) {
    return 0.5 // Default to middle value if not enough samples
  }

  const peakWindow = audioData.slice(peakStart, peakEnd)
  const decayWindow = audioData.slice(decayStart, decayEnd)

  // Calculate RMS for each window
  let peakRms = 0.1, decayRms = 0.05 // defaults
  try {
    const peakVector = essentia.arrayToVector(peakWindow)
    const peakResult = essentia.RMS(peakVector)
    peakRms = peakResult.rms
  } catch (e) {
    log.debug('Peak RMS calculation failed', { error: String(e) })
  }
  try {
    const decayVector = essentia.arrayToVector(decayWindow)
    const decayResult = essentia.RMS(decayVector)
    decayRms = decayResult.rms
  } catch (e) {
    log.debug('Decay RMS calculation failed', { error: String(e) })
  }

  // Calculate ratio (clamp to 0-1 range)
  // Avoid division by zero
  if (peakRms <= 0 || !Number.isFinite(peakRms)) {
    return 0.5
  }

  const ratio = decayRms / peakRms
  return Math.min(1, Math.max(0, ratio))
}

/**
 * Calculate confidence score for a potential strike
 *
 * Golf ball strikes have characteristic spectral properties:
 * - Spectral centroid around 3000-4000 Hz (bright, percussive)
 * - Moderate spectral flatness (not pure tone, not white noise)
 * - Sufficient energy (RMS)
 * - Fast decay (low decay ratio) - distinguishes from practice swings
 */
function calculateConfidence(
  centroid: number,
  flatness: number,
  rms: number,
  decayRatio: number
): number {
  // Centroid score: golf strikes typically have centroid around 3500 Hz
  // Score decreases as centroid deviates from target
  const targetCentroid = 3500
  const centroidDiff = Math.abs(centroid - targetCentroid)
  const centroidScore = Math.max(0, 1 - centroidDiff / 3000)

  // Flatness score: moderate flatness is characteristic of percussive sounds
  // Too low = tonal (not a strike), too high = noise
  let flatnessScore: number
  if (flatness >= 0.1 && flatness <= 0.6) {
    flatnessScore = 1.0
  } else if (flatness < 0.1) {
    flatnessScore = flatness / 0.1 // Ramp up from 0
  } else {
    flatnessScore = Math.max(0, 1 - (flatness - 0.6) / 0.4) // Ramp down from 0.6
  }

  // RMS score: need sufficient energy for a real strike
  // Normalize RMS (typical range 0.01-0.3 for strikes)
  const rmsScore = Number.isFinite(rms) ? Math.min(1, rms / 0.1) : 0

  // Decay score: lower decay ratio = faster decay = more likely real strike
  // Real ball strikes typically have decay ratio < 0.4
  // Practice swings (whoosh) typically have decay ratio > 0.6
  const decayScore = 1 - decayRatio

  // Weighted combination
  // Centroid and decay are most important, followed by RMS, then flatness
  return centroidScore * 0.3 + decayScore * 0.3 + rmsScore * 0.25 + flatnessScore * 0.15
}
