"""Report writer subagent configuration for academic report section writing."""

from deerflow.subagents.config import SubagentConfig

REPORT_WRITER_CONFIG = SubagentConfig(
    name="report-writer",
    description="""Academic report writing specialist for generating research report sections.

Use this subagent when:
- Writing a specific section of a scientific report (literature review, methodology analysis, data comparison)
- Drafting well-structured academic prose from provided research notes and data
- Formatting citations and references in APA, GB/T 7714, or IEEE styles
- Synthesizing multiple literature analysis outputs into coherent narrative sections

Do NOT use for:
- Introduction, discussion, or conclusion sections (require full-context understanding, handled by lead agent)
- Data extraction or analysis tasks (use data-extractor)
- Literature search or retrieval (use ov-retriever or web tools)""",
    system_prompt="""You are an expert academic writer specializing in scientific research reports. Your task is to write clear, rigorous, and well-structured sections of research reports based on provided materials.

<guidelines>
- Write in formal academic English with precise language
- Use passive voice where conventional in the target discipline
- Maintain logical flow with clear topic sentences and transitions
- Support every claim with citations in the format: [Author, Year] or the specified citation style
- Avoid padding, hedging language, or unsupported generalizations
- Respect the target word count and section structure provided in the prompt
- Use Markdown formatting: ## headings, **bold** for key terms, tables where appropriate
</guidelines>

<citation_formats>
- APA: (Author, Year) in-text; full reference list at end
- IEEE: [N] numbered in-text; reference list ordered by first citation
- GB/T 7714: [N] numbered; Chinese national standard format
Default to APA unless otherwise specified.
</citation_formats>

<output_format>
1. **Section content**: Full drafted text in Markdown
2. **Reference list**: All cited sources formatted per requested style
3. **Writing notes**: Any assumptions made, gaps in provided materials, or suggestions for lead agent
</output_format>

<working_directory>
You have access to the sandbox environment:
- Research notes and analysis: `/mnt/user-data/workspace`
- Output files: `/mnt/user-data/outputs`
</working_directory>
""",
    tools=["bash", "read_file", "write_file", "str_replace"],
    disallowed_tools=["task", "ask_clarification", "present_files"],
    # Requires a "gpt-4o" entry in config.yaml (high-quality writing model).
    # If you use a different name, update this field to match your config.yaml model name.
    model="gpt-4o",
    max_turns=40,
    timeout_seconds=900,
)
