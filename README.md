# 🎓 edu-flow: Motor de Orquestación Proyecto Alere

![Alere Banner](https://img.shields.io/badge/Project-Alere-blueviolet?style=for-the-badge)
![Role](https://img.shields.io/badge/Architecture-Solutions_Senior-blue?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Orchestration_Engine_Active-success?style=for-the-badge)

**An open-source SuperAgent harness that researches, edits, and creates educational resources. With the help of sandboxes, memories, tools, skills and subagents, it handles different levels of tasks that could take minutes to hours.**

**edu-flow** es un motor de orquestación de contenidos de próxima generación, diseñado específicamente para el **Proyecto Alere**. Basado en el harness de agentes `edu-flow`, esta versión ha sido transformada para automatizar la creación de **Situaciones de Aprendizaje (SIA)** de alto impacto pedagógico.

## 🚀 Misión del Sistema
Automatizar el ciclo de vida del contenido educativo, desde el desequilibrio cognitivo inicial hasta la exportación multi-plataforma, garantizando la movilización de saberes y la trazabilidad competencial (SCC).

---

## 🏗️ Modelo de Datos: SIA Core (5 Nodos)

El sistema orquestra cada SIA a través de cinco nodos críticos fundamentales para el aprendizaje significativo:

1.  **Nodo 1: Activación (Desequilibrio Cognitivo)**
    *   *Acción:* Dispara la creación de un video conceptual mediante la API de **Google Veo** o **Seedance**.
    *   *Objetivo:* Generar curiosidad inmediata mediante situaciones reales impactantes.
2.  **Nodo 2: Contexto y Pregunta Generadora**
    *   *Acción:* Genera escenarios simulados que sitúan el problema en la realidad del estudiante.
3.  **Nodo 3: Desafío Movilizador (Reto)**
    *   *Acción:* Define el núcleo pedagógico que demanda la aplicación activa de conocimientos.
4.  **Nodo 4: Secuencia de Sesiones**
    *   *Acción:* Bloques de 4-5 sesiones con metodologías activas (ABP, Flipped Classroom, etc.).
5.  **Nodo 5: Producto Final y Metacognición**
    *   *Acción:* Generación de rúbricas de evaluación auténtica y protocolos de reflexión (Check-ins).

---

## 🛠️ AI Toolchain (Integración de Activos)

edu-flow sustituye recursos genéricos por una cadena de herramientas de IA especializada:

*   **Video de Partida:** Renderizado de situaciones reales con **Google Veo**.
*   **Audio Narrativo:** Narrativas técnicas de alta fidelidad con **Google ProducerAI (Lyra)**.
*   **Audio Pedagógico:** Canciones basadas en datos curiosos ("Detrás del dato") creadas con **Suno**.
*   **Interactivos Dinámicos:** Exportación de lógica de nodos hacia componentes de **Rive** (diseñados en Figma) para manipulación de vectores y diagramas de flujo.

---

## 🏷️ Sistema de Etiquetado Competencial (SCC)

Cada pieza de contenido es mapeada automáticamente con los descriptores operativos de las **8 Competencias Clave de Alere**:

1.  Comunicativa
2.  Matemática-Científica
3.  Digital
4.  Innovación
5.  Ciudadana
6.  **Socioemocional** (Obligatoria: ConCiencia)
7.  **Cultural-Artística** (Obligatoria: ConecARTE)
8.  Corporal

> [!IMPORTANT]
> El flujo de generación se bloquea automáticamente si falta el componente de **"ConCiencia Socioemocional"** o el de **"ConecARTE"**.

---

## 📤 Arquitectura de Salida Multi-Plataforma

El exportador de edu-flow distribuye el contenido procesado en tres destinos clave:

*   **Wiki Dinámica (Bridge Box):** Repositorio técnico bilingüe y consulta de saberes.
*   **Google Stitch (Frontend Estudiantes):** Interfaces diferenciadas para Niños y Adolescentes que consumen el JSON de la SIA.
*   **Dashboard Docente:** Generador inteligente de planes de lección y laboratorios pedagógicos.

---

## 🛠️ Instalación y Desarrollo

### Requisitos
*   Node.js 22+
*   Python 3.12+ (uv recomendado)
*   API Keys: GEMINI_API_KEY (para Veo), SUNO_API_KEY.

### Inicio Rápido
1. `make install`
2. Configura tus modelos en `config.yaml`.
3. Usa la skill `alere-sia-creator` para empezar a orquestar.

---
*Desarrollado por el Equipo de Arquitectura de Soluciones Senior y Líderes EdTech para Proyecto Alere.*
