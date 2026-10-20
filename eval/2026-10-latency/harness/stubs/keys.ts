// Harness stub: keys from the environment only (never the app's data dir).
export function getKey(provider: string): string | null {
  if (provider === 'gemini') return process.env.GEMINI_API_KEY || null
  if (provider === 'azure' || provider === 'azure-foundry') return process.env.AZURE_SPEECH_KEY || null
  if (provider === 'azure-gemini') return process.env.GEMINI_API_KEY ? process.env.AZURE_SPEECH_KEY || null : null
  return null
}
