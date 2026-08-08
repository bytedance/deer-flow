CyliaTales Cost Control & $150/month Model Budget Guidance

You have an initial $150 budget for LLM and image generation. That is tight but workable for prototyping and early demos if we control spend aggressively.

Strategy to run on $150/month
1. Use cheap preview paths, reserve high-res generations for paid customers only
   - Previews: generate low-res images (256–512px) locally or via cheaper endpoints for live editing
   - High-res: gated behind credits; only pay for hi-res when export is requested
2. Prefer open-source or inexpensive endpoints for LLMs and vision during alpha
   - LLM: use Mistral/LLama via smaller hosted endpoints or Hugging Face inference with token limits; use short prompts and RAG sparingly
   - Vision: use small/faster SD variants for previews; offload SDXL high-res to on-demand paid instances
3. Pre-generate library & templates server-side
   - Pre-render many of the 60 templates and outfit mockups as marketing assets (one-time cost) and serve them as static assets
   - This reduces per-user image generation dramatically
4. Cache aggressively and reuse assets
   - Cache LLM outputs for same inputs, cache generated images per character/style/pose parameters
5. Throttle & quota per user
   - Set default preview generation free but limited (e.g., 20 previews/day), require credits for more
6. Offer paid premium renders and white-glove services for immediate revenue
   - Use initial $150 to create a few compelling demo assets and two white-glove deliverables to sell
7. Monitor and autoscale smartly
   - Track GPU job queue length and cost per render; scale up only for paid jobs

Quick provider recommendations (cost-conscious)
- Hosted previews: Replicate (small models), Stability AI (paid but competitive for image API), Hugging Face Inference (cheaper for some open models)
- On-demand high-res: Runpod, Vast.ai or Lambda Labs spot instances for SDXL jobs
- LLM: Mistral/Claude/OpenAI savings – minimize calls; prefer Mistral (lower cost) for many tasks and OpenAI for polishing when necessary

Operational controls to implement now
- Spend monitoring: alert when spend reaches 60%, 80%, and 95% of budget
- Default to preview pipelines and deny high-res renders until payment/credits
- Queue & prioritization: white-glove jobs drain from dedicated budget; bill customers before run

Deliverables I will add to the repo now (if you confirm)
- docs/LEMON_SQUEEZY.md (webhook skeleton + mapping)
- docs/PRICING_AND_GTM.md (this file already added)
- Add environment variables README with placeholders for model providers and Lemon API keys

