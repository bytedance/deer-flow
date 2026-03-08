# 🎓 edu-flow: Orchestration Engine for Proyecto Alere

![Alere Banner](https://img.shields.io/badge/Project-Alere-blueviolet?style=for-the-badge)
![Role](https://img.shields.io/badge/Architecture-Solutions_Senior-blue?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Orchestration_Engine_Active-success?style=for-the-badge)

**An open-source SuperAgent harness that researches, edits, and creates educational resources. With the help of sandboxes, memories, tools, skills and subagents, it handles different levels of tasks that could take minutes to hours.**

**edu-flow** is a next-generation content orchestration engine, designed specifically for **Proyecto Alere**. Based on the `edu-flow` agent harness, this version has been transformed to automate the creation of **Learning Situations (SIA)** with high pedagogical impact.

## 🚀 System Mission
Automate the educational content lifecycle, from initial cognitive imbalance to multi-platform export, ensuring knowledge mobilization and competency traceability (SCC).

---

## 🏗️ Data Model: SIA Core (5 Nodes)

The system orchestrates each SIA through five fundamental critical nodes for meaningful learning:

1.  **Node 1: Activation (Cognitive Imbalance)**
    *   *Action:* Triggers the creation of a conceptual video through the **Google Veo** or **Seedance** API.
    *   *Objective:* Generate immediate curiosity through impactful real-world situations.
2.  **Node 2: Context and Driving Question**
    *   *Action:* Generates simulated scenarios that place the problem in the student's reality.
3.  **Node 3: Mobilizing Challenge (Task)**
    *   *Action:* Defines the pedagogical core that demands active application of knowledge.
4.  **Node 4: Session Sequence**
    *   *Action:* Blocks of 4-5 sessions with active methodologies (PBL, Flipped Classroom, etc.).
5.  **Node 5: Final Product and Metacognition**
    *   *Action:* Generation of authentic assessment rubrics and reflection protocols (Check-ins).

---

## 🛠️ AI Toolchain (Asset Integration)

edu-flow replaces generic resources with a specialized AI toolchain:

*   **Starting Video:** Rendering of real situations with **Google Veo**.
*   **Narrative Audio:** High-fidelity technical narratives with **Google ProducerAI (Lyra)**.
*   **Pedagogical Audio:** Songs based on curious data ("Behind the data") created with **Suno**.
*   **Dynamic Interactives:** Export of node logic to **Rive** components (designed in Figma) for vector manipulation and flowcharts.

---

## 🏷️ Competency Labeling System (SCC)

Each piece of content is automatically mapped to the operational descriptors of the **8 Alere Key Competencies**:

1.  Communicative
2.  Mathematical-Scientific
3.  Digital
4.  Innovation
5.  Citizen
6.  **Socioemotional** (Mandatory: ConCiencia)
7.  **Cultural-Artistic** (Mandatory: ConecARTE)
8.  Corporal

> [!IMPORTANT]
> The generation flow is automatically blocked if the **"ConCiencia Socioemocional"** or **"ConecARTE"** component is missing.

---

## 📤 Multi-Platform Output Architecture

The edu-flow exporter distributes processed content to three key destinations:

*   **Dynamic Wiki (Bridge Box):** Bilingual technical repository and knowledge reference.
*   **Google Stitch (Student Frontend):** Differentiated interfaces for Kids and Teens consuming the SIA JSON.
*   **Dashboard Teacher:** Intelligent lesson plan generator and pedagogical laboratories.

---

## 🛠️ Installation and Development

### Prerequisites

To ensure a smooth and secure installation, verify you have the following tools installed:
- **Node.js 22+**
- **pnpm 10+** (Fast and efficient package manager for the frontend)
- **Python 3.12+**
- **uv** (Extremely fast Python package manager and resolver)
- **Docker** (Recommended for sandboxed tool execution)
- **Nginx** (Required for the unified local development endpoint)

### Quick Start Guide

Follow these steps to set up your environment:

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/Editorenbici/edu-flow.git
    cd edu-flow
    ```

2.  **Verify dependencies**:
    Run the built-in check tool to ensure your environment is ready:
    ```bash
    make check
    ```

3.  **Initialize configuration**:
    Generate your local configuration files from templates:
    ```bash
    make config
    ```
    This creates `config.yaml` and `.env` in the project root.

4.  **Configure API Keys**:
    Edit the `.env` file and add your credentials:
    ```bash
    GEMINI_API_KEY=your_key_here
    SUNO_API_KEY=your_key_here
    # Add other provider keys as needed (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)
    ```

5.  **Install dependencies**:
    ```bash
    make install
    ```

6.  **Start the development server**:
    The easiest way to run all services (Backend, Frontend, and Nginx) is:
    ```bash
    make dev
    ```
    Once running, access the application at **http://localhost:2026**.

### Deployment Options

- **Local Execution**: Runs directly on your host machine. Best for rapid development.
- **Docker (Recommended)**: Uses containers for complete isolation and security. Run `make docker-init` followed by `make docker-start`.

For detailed architecture and configuration options, see the [Backend Documentation](backend/README.md) and [Configuration Guide](backend/docs/CONFIGURATION.md).

---
*Developed by Maya Educación for Proyecto Alere.*
