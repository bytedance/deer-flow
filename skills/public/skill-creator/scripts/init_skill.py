#   !/usr/bin/env python3


"""
Skill Initializer - Creates a 新建 skill from template

Usage:
    init_skill.py <skill-名称> --路径 <路径>

Examples:
    init_skill.py my-新建-skill --路径 skills/public
    init_skill.py my-接口-helper --路径 skills/private
    init_skill.py custom-skill --路径 /custom/location
"""

import sys
from pathlib import Path


SKILL_TEMPLATE = """---
名称: {skill_name}
描述: [TODO: Complete and informative explanation of what the skill does and when to use it. Include WHEN to use this skill - specific scenarios, 文件 types, or tasks that trigger it.]
---

#    {skill_title}



#   # Overview



[TODO: 1-2 sentences explaining what this skill enables]

#   # Structuring This Skill



[TODO: Choose the structure that best fits this skill's purpose. Common patterns:

**1. Workflow-Based** (best for sequential processes)
- Works well when there are clear step-by-step procedures
- Example: DOCX skill with "Workflow Decision Tree" → "Reading" → "Creating" → "Editing"
- Structure: #   # Overview → ## Workflow Decision Tree → ## Step 1 → ## Step 2...



**2. Task-Based** (best for 工具 collections)
- Works well when the skill offers different operations/capabilities
- Example: PDF skill with "Quick Start" → "Merge PDFs" → "Split PDFs" → "Extract Text"
- Structure: #   # Overview → ## Quick Start → ## Task Category 1 → ## Task Category 2...



**3. Reference/Guidelines** (best for standards or specifications)
- Works well for brand guidelines, coding standards, or requirements
- Example: Brand styling with "Brand Guidelines" → "Colors" → "Typography" → "Features"
- Structure: #   # Overview → ## Guidelines → ## Specifications → ## Usage...



**4. Capabilities-Based** (best for integrated systems)
- Works well when the skill provides multiple interrelated features
- Example: Product Management with "Core Capabilities" → numbered capability 列表
- Structure: #   # Overview → ## Core Capabilities → ### 1. Feature → ### 2. Feature...



Patterns can be mixed and matched as needed. Most skills combine patterns (e.g., 开始 with task-based, add workflow for 复杂 operations).

Delete this entire "Structuring This Skill" section when done - it's just guidance.]

#   # [TODO: Replace with the 第一 main section based on chosen structure]



[TODO: Add content here. See examples in existing skills:
- Code samples for technical skills
- Decision trees for 复杂 workflows
- Concrete examples with realistic 用户 requests
- References to scripts/templates/references as needed]

#   # Resources



This skill includes 示例 resource directories that demonstrate how to organize different types of bundled resources:

#   ## scripts/


Executable code (Python/Bash/etc.) that can be 运行 directly to perform specific operations.

**Examples from other skills:**
- PDF skill: `fill_fillable_fields.py`, `extract_form_field_info.py` - utilities for PDF manipulation
- DOCX skill: `document.py`, `utilities.py` - Python modules for document processing

**Appropriate for:** Python scripts, shell scripts, or any executable code that performs automation, 数据 processing, or specific operations.

**Note:** Scripts may be executed without 加载中 into context, but can still be read by Claude for patching or 环境 adjustments.

#   ## references/


Documentation and reference material intended to be loaded into context to inform Claude's 处理 and thinking.

**Examples from other skills:**
- Product management: `communication.md`, `context_building.md` - detailed workflow guides
- BigQuery: API reference documentation and query examples
- Finance: Schema documentation, company policies

**Appropriate for:** In-depth documentation, API references, 数据库 schemas, comprehensive guides, or any detailed information that Claude should reference while working.

#   ## assets/


Files not intended to be loaded into context, but rather used within the 输出 Claude produces.

**Examples from other skills:**
- Brand styling: PowerPoint template files (.pptx), logo files
- Frontend builder: HTML/React boilerplate 项目 directories
- Typography: Font files (.ttf, .woff2)

**Appropriate for:** Templates, boilerplate code, document templates, images, icons, fonts, or any files meant to be copied or used in the final 输出.

---

**Any unneeded directories can be deleted.** Not every skill requires all three types of resources.
"""

EXAMPLE_SCRIPT = '''#!/usr/bin/env python3
"""
Example helper script for {skill_name}

This is a placeholder script that can be executed directly.
Replace with actual implementation or 删除 if not needed.

Example real scripts from other skills:
- pdf/scripts/fill_fillable_fields.py - Fills PDF form fields
- pdf/scripts/convert_pdf_to_images.py - Converts PDF pages to images
"""

def main():
    print("This is an 示例 script for {skill_name}")
    #    TODO: Add actual script logic here


    #    This could be 数据 processing, 文件 conversion, API calls, etc.



if __name__ == "__main__":
    main()
'''

EXAMPLE_REFERENCE = """# Reference Documentation for {skill_title}

This is a placeholder for detailed reference documentation.
Replace with actual reference content or 删除 if not needed.

Example real reference docs from other skills:
- product-management/references/communication.md - Comprehensive guide for status updates
- product-management/references/context_building.md - Deep-dive on gathering context
- bigquery/references/ - API references and query examples

#   # When Reference Docs Are Useful



Reference docs are ideal for:
- Comprehensive API documentation
- Detailed workflow guides
- Complex multi-step processes
- Information too lengthy for main SKILL.md
- Content that's only needed for specific use cases

#   # Structure Suggestions



#   ## API Reference Example


- Overview
- Authentication
- Endpoints with examples
- 错误 codes
- Rate limits

#   ## Workflow Guide Example


- Prerequisites
- Step-by-step instructions
- Common patterns
- Troubleshooting
- Best practices
"""

EXAMPLE_ASSET = """# Example Asset File

This placeholder represents where asset files would be stored.
Replace with actual asset files (templates, images, fonts, etc.) or 删除 if not needed.

Asset files are NOT intended to be loaded into context, but rather used within
the 输出 Claude produces.

Example asset files from other skills:
- Brand guidelines: logo.png, slides_template.pptx
- Frontend builder: hello-world/ 目录 with HTML/React boilerplate
- Typography: custom-font.ttf, font-family.woff2
- Data: sample_data.csv, test_dataset.json

#   # Common Asset Types



- Templates: .pptx, .docx, boilerplate directories
- Images: .png, .jpg, .svg, .gif
- Fonts: .ttf, .otf, .woff, .woff2
- Boilerplate code: Project directories, starter files
- Icons: .ico, .svg
- Data files: .csv, .json, .xml, .yaml

Note: This is a text placeholder. Actual assets can be any 文件 类型.
"""


def title_case_skill_name(skill_name):
    """Convert hyphenated skill 名称 to Title Case for display."""
    return ' '.join(word.capitalize() for word in skill_name.split('-'))


def init_skill(skill_name, path):
    """
    Initialize a 新建 skill 目录 with template SKILL.md.

    Args:
        skill_name: Name of the skill
        路径: Path where the skill 目录 should be created

    Returns:
        Path to created skill 目录, or None if 错误
    """
    #    Determine skill 目录 路径


    skill_dir = Path(path).resolve() / skill_name

    #    Check 如果 目录 already exists


    if skill_dir.exists():
        print(f"❌ Error: Skill directory already exists: {skill_dir}")
        return None

    #    Create skill 目录


    try:
        skill_dir.mkdir(parents=True, exist_ok=False)
        print(f"✅ Created skill directory: {skill_dir}")
    except Exception as e:
        print(f"❌ Error creating directory: {e}")
        return None

    #    Create SKILL.md from template


    skill_title = title_case_skill_name(skill_name)
    skill_content = SKILL_TEMPLATE.format(
        skill_name=skill_name,
        skill_title=skill_title
    )

    skill_md_path = skill_dir / 'SKILL.md'
    try:
        skill_md_path.write_text(skill_content)
        print("✅ Created SKILL.md")
    except Exception as e:
        print(f"❌ Error creating SKILL.md: {e}")
        return None

    #    Create resource directories with 示例 files


    try:
        #    Create scripts/ 目录 with 示例 script


        scripts_dir = skill_dir / 'scripts'
        scripts_dir.mkdir(exist_ok=True)
        example_script = scripts_dir / 'example.py'
        example_script.write_text(EXAMPLE_SCRIPT.format(skill_name=skill_name))
        example_script.chmod(0o755)
        print("✅ Created scripts/example.py")

        #    Create references/ 目录 with 示例 reference doc


        references_dir = skill_dir / 'references'
        references_dir.mkdir(exist_ok=True)
        example_reference = references_dir / 'api_reference.md'
        example_reference.write_text(EXAMPLE_REFERENCE.format(skill_title=skill_title))
        print("✅ Created references/api_reference.md")

        #    Create assets/ 目录 with 示例 asset placeholder


        assets_dir = skill_dir / 'assets'
        assets_dir.mkdir(exist_ok=True)
        example_asset = assets_dir / 'example_asset.txt'
        example_asset.write_text(EXAMPLE_ASSET)
        print("✅ Created assets/example_asset.txt")
    except Exception as e:
        print(f"❌ Error creating resource directories: {e}")
        return None

    #    Print 下一个 steps


    print(f"\n✅ Skill '{skill_name}' initialized successfully at {skill_dir}")
    print("\nNext steps:")
    print("1. Edit SKILL.md to complete the TODO items and update the description")
    print("2. Customize or delete the example files in scripts/, references/, and assets/")
    print("3. Run the validator when ready to check the skill structure")

    return skill_dir


def main():
    if len(sys.argv) < 4 or sys.argv[2] != '--path':
        print("Usage: init_skill.py <skill-name> --path <path>")
        print("\nSkill name requirements:")
        print("  - Hyphen-case identifier (e.g., 'data-analyzer')")
        print("  - Lowercase letters, digits, and hyphens only")
        print("  - Max 40 characters")
        print("  - Must match directory name exactly")
        print("\nExamples:")
        print("  init_skill.py my-new-skill --path skills/public")
        print("  init_skill.py my-api-helper --path skills/private")
        print("  init_skill.py custom-skill --path /custom/location")
        sys.exit(1)

    skill_name = sys.argv[1]
    path = sys.argv[3]

    print(f"🚀 Initializing skill: {skill_name}")
    print(f"   Location: {path}")
    print()

    result = init_skill(skill_name, path)

    if result:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
