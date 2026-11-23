// Script only the model's decisions. DSH owns tool execution and tool history.
const { LlmAdapter } = await import(process.env.SPIKE_LLM_MODULE)
export const name = 'coding-fixture'
export const inject = ['llm']

class CodingFixture extends LlmAdapter {
  async *stream({ messages }) {
    const prompt = messages.filter(m => m.role === 'user').flatMap(m => m.content)
      .findLast(b => b.type === 'text' && b.text.startsWith('Probe:'))?.text
    const results = messages.filter(m => m.role === 'tool')
    const receipt = JSON.stringify(results).match(/PASS-[a-f0-9]{24}/)?.[0]
    let calls = [
      ['write', { file_path: 'sum.cjs', content: 'module.exports = (a, b) => a + b\n' }],
      ['bash', { description: 'Run the repository regression test', command: 'node test.cjs' }],
    ]
    const currentResults = messages.slice(messages.findLastIndex(m => m.role === 'user')).filter(m => m.role === 'tool')
    if (prompt === 'Probe: fix only') calls = calls.slice(0, 1)
    else if (prompt === 'Probe: record test receipt') calls = [['read', { file_path: 'receipt.txt' }]]
    else if (prompt !== 'Probe: fix and test') calls = []
    if (currentResults.length < calls.length) {
      const [name, args] = calls[currentResults.length]
      const call = { type: 'tool-call', id: 'coding-' + name, name, arguments: JSON.stringify(args) }
      yield { type: 'block-start', index: 0, blockType: 'tool-call' }
      yield { type: 'tool-call-delta', index: 0, id: call.id, name, argumentsDelta: call.arguments }
      yield { type: 'block-end', index: 0, block: call }
      yield { type: 'finish', reason: { kind: 'tool-calls' } }
      return
    }
    let text = receipt ?? 'No test receipt in history.'
    if (prompt === 'Probe: fix and test') text = receipt ? 'Tests passed.' : 'Test receipt missing.'
    if (prompt === 'Probe: fix only') text = 'Edit requested.'
    if (prompt === 'Probe: record test receipt') text = receipt ? 'Receipt recorded.' : 'Receipt missing.'
    yield { type: 'block-start', index: 0, blockType: 'text' }
    yield { type: 'text-delta', index: 0, text }
    yield { type: 'block-end', index: 0, block: { type: 'text', text } }
    yield { type: 'finish', reason: { kind: 'stop' } }
  }
}

export function apply(ctx) {
  ctx.llm.registerAdapter(['coding-fixture'], new CodingFixture())
}
