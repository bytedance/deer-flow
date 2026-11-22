// A deterministic model only. The DSH loop, native read tool and Session store are real.
import { setTimeout as delay } from 'node:timers/promises'

const { LlmAdapter } = await import(process.env.SPIKE_LLM_MODULE)
export const name = 'rfc-7840-fixture'
export const inject = ['llm']

class QuoteFixture extends LlmAdapter {
  async *stream({ messages, signal }) {
    const inputs = messages.filter(m => m.role === 'user').flatMap(m => m.content)
    const task = inputs.findLast(b => b.type === 'text' && b.text.startsWith('Probe:'))?.text
    if (task === 'Probe: wait') {
      await delay(60_000, undefined, { signal })
    }
    if (task === 'Probe: crash') {
      process.kill(process.pid, 'SIGKILL')
    }
    if (task === 'Probe: fail') {
      yield { type: 'finish', reason: { kind: 'error', failure: { code: 'INVALID_CREDENTIAL', message: 'fixture failure' } } }
      return
    }
    const tool = messages.findLast(m => m.role === 'tool')
    if (task === 'Probe: read quote' && !tool) {
      const call = { type: 'tool-call', id: 'read-quote', name: 'read', arguments: JSON.stringify({ file_path: 'quote.txt' }) }
      yield { type: 'block-start', index: 0, blockType: 'tool-call' }
      yield { type: 'tool-call-delta', index: 0, id: call.id, name: call.name, argumentsDelta: call.arguments }
      yield { type: 'block-end', index: 0, block: call }
      yield { type: 'finish', reason: { kind: 'tool-calls' } }
      return
    }
    const quote = JSON.stringify(tool?.content ?? []).match(/QUOTE-[a-f0-9]+/)?.[0]
    const text = task === 'Probe: read quote' ? 'Quote recorded.' : (quote ?? 'No quote in history.')
    yield { type: 'block-start', index: 0, blockType: 'text' }
    yield { type: 'text-delta', index: 0, text }
    yield { type: 'block-end', index: 0, block: { type: 'text', text } }
    yield { type: 'finish', reason: { kind: 'stop' } }
  }
}

export function apply(ctx) {
  ctx.llm.registerAdapter(['quote-fixture'], new QuoteFixture())
}
