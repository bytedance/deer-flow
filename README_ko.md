# 🦌 DeerFlow - 2.0

[English](README.md) | [中文](README_zh.md) | [日本語](README_ja.md) | [Français](README_fr.md) | [Русский](README_ru.md) | [Português](README_pt.md) | 한국어

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](backend/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-22%2B-339933?logo=node.js&logoColor=white)](Makefile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

<a href="https://trendshift.io/repositories/14699" target="_blank"><img src="https://trendshift.io/api/badge/repositories/14699" alt="bytedance%2Fdeer-flow | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
> 2026년 2월 28일, DeerFlow는 버전 2 출시 이후 GitHub Trending에서 🏆 1위를 차지했습니다. 놀라운 커뮤니티 여러분께 진심으로 감사드립니다. 여러분이 이 일을 해냈습니다! 💪🔥

DeerFlow(**D**eep **E**xploration and **E**fficient **R**esearch **Flow**)는 **서브에이전트**, **메모리**, **샌드박스**를 오케스트레이션하여 거의 모든 일을 해낼 수 있는 오픈소스 **슈퍼 에이전트 하네스**이며, **확장 가능한 스킬**로 동작합니다.

https://github.com/user-attachments/assets/a8bcadc4-e040-4cf2-8fda-dd768b999c18

> [!NOTE]
> **DeerFlow 2.0은 처음부터 완전히 새로 작성되었습니다.** v1과 공유하는 코드는 전혀 없습니다. 기존 Deep Research 프레임워크를 찾고 있다면 [`1.x` 브랜치](https://github.com/bytedance/deer-flow/tree/main-1.x)를 참고하세요. 이 프레임워크는 해당 브랜치에서 계속 유지 관리되며, 그 브랜치에 대한 기여도 여전히 환영합니다. 활발한 개발은 2.0으로 옮겨졌습니다.

## 공식 웹사이트

[**공식 웹사이트**](https://deerflow.tech)에서 더 자세히 알아보고 **실제 데모**를 확인하세요.
랜딩 페이지의 사례 연구는 허용 목록에 등록된 읽기 전용 쇼케이스로 열리며, 로그인이 필요하지 않습니다.

## 자매 프로젝트

<img width="446" height="280" alt="image" align="middle" src="https://github.com/user-attachments/assets/077edef4-d560-41af-bb0d-d0a5f14fcc20" />

- [**LLM Space**](https://github.com/deer-flow/llm-space) - DeerFlow를 뒷받침하는 비밀 무기를 만나 보세요. 에이전트 아이디어를 프로토타이핑하고, 하네스의 각 단계를 살펴보고, 실패를 재생(replay)하고, 성능을 벤치마크할 수 있는 하나의 데스크톱 도구입니다.

## ByteDance Volcengine의 Coding Plan

- DeerFlow 실행에는 Doubao-Seed-2.0-Code, DeepSeek v3.2, Kimi 2.5 사용을 적극 권장합니다
- [자세히 알아보기](https://www.byteplus.com/en/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)
- [中国大陆地区的开发者请点击这里](https://www.volcengine.com/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)

## InfoQuest

DeerFlow는 BytePlus가 독자적으로 개발한 지능형 검색 및 크롤링 도구 세트를 새롭게 통합했습니다 — [InfoQuest (무료 온라인 체험 지원)](https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest)

<a href="https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest" target="_blank">
  <img
    src="https://sf16-sg.tiktokcdn.com/obj/eden-sg/hubseh7bsbps/20251208-160108.png"   alt="InfoQuest_banner"
  />
</a>

---

## 한 줄 에이전트 설정

Claude Code, Codex, Cursor, Windsurf 또는 다른 코딩 에이전트를 사용한다면, 설정 지침을 한 문장으로 전달할 수 있습니다:

```text
Help me clone DeerFlow if needed, then bootstrap it for local development by following https://raw.githubusercontent.com/bytedance/deer-flow/main/Install.md
```

이 프롬프트는 코딩 에이전트용입니다. 에이전트에게 필요하면 저장소를 클론하고, 가능하면 Docker를 선택하며, 다음에 실행할 정확한 명령과 사용자가 아직 제공해야 하는 누락된 설정을 알려 준 뒤 멈추도록 지시합니다.

## 빠른 시작

```bash
git clone https://github.com/bytedance/deer-flow.git
cd deer-flow
make setup          # 대화형 마법사로 config.yaml과 .env를 생성합니다(약 2분).
```

그런 다음 Docker(권장)로 DeerFlow를 시작하거나 로컬에서 실행하세요.

```bash
# Docker
make docker-init    # 샌드박스 이미지 가져오기(처음 실행하거나 이미지가 업데이트될 때)
make docker-start   # 서비스 시작
```

```bash
# 로컬 개발
make check          # Node.js 22+, pnpm, uv, nginx 확인
make install
make dev
```

로컬 명령은 `frontend/package.json`에 고정된 pnpm 버전을 사용합니다.
`PATH`에 다른 버전의 전역 pnpm이 있으면 Corepack을 사용할 수 있을 때 이를 사용합니다.
Corepack을 사용할 수 없으면 프론트엔드 의존성을 설치하기 전에 버전이 일치하지 않는다고 알립니다.

모델 자격 증명을 설정한 뒤 `make doctor`를 실행하세요. 예시 API 키가 남아 있으면
설정이 완료되지 않았다고 표시합니다. 모델 호출을 테스트하기 전에 실제 키로 바꾸세요.

<http://localhost:2026>에 접속하세요.

- 전체 설정 옵션, 프로바이더 및 수동 설정은 [설정](docs/guide/configuration.md)을 참고하세요.
- Docker 상세 설정, 배포 규모 산정, 업그레이드, 시작 모드 및 프로덕션 배포는 [애플리케이션 실행](docs/guide/deployment.md)을 참고하세요.
- 서버에서 실행하거나 로컬호스트 외부에 공개하려면 먼저 [보안 고지](docs/guide/security.md)를 읽어 주세요.

## Deep Research에서 슈퍼 에이전트 하네스로

DeerFlow는 Deep Research 프레임워크로 시작했고, 커뮤니티는 이를 마음껏 활용했습니다. 출시 이후 개발자들은 리서치의 범위를 훨씬 넘어 데이터 파이프라인 구축, 슬라이드 덱 생성, 대시보드 구성, 콘텐츠 워크플로 자동화에까지 DeerFlow를 활용했습니다. 저희가 전혀 예상하지 못한 일들이었습니다.

이를 통해 중요한 사실을 알게 되었습니다. DeerFlow는 단순한 리서치 도구가 아니었습니다. 에이전트가 실제로 일을 해낼 수 있도록 인프라를 제공하는 런타임, 즉 **하네스**였습니다.

그래서 저희는 DeerFlow를 처음부터 다시 만들었습니다.

DeerFlow 2.0은 더 이상 직접 엮어서 조립하는 프레임워크가 아닙니다. 필요한 것이 모두 갖춰져 있고 완전히 확장 가능한 슈퍼 에이전트 하네스입니다. LangGraph와 LangChain을 기반으로 하며, 에이전트에 필요한 모든 것을 기본 제공합니다. 파일 시스템, 메모리, 스킬, 샌드박스를 인식하는 실행, 그리고 복잡한 다단계 작업을 위해 계획을 세우고 서브에이전트를 생성하는 능력까지 포함됩니다.

그대로 사용하세요. 아니면 마음껏 뜯어고쳐 여러분만의 것으로 만드세요.

## 가이드

각 가이드에서 해당 주제의 자세한 내용을 확인할 수 있습니다.

| 주제 | 가이드 |
| --- | --- |
| 모델, 프로바이더, `config.yaml`, 환경 변수 | [설정](docs/guide/configuration.md) |
| DeepSeek 웹 검색, thinking 모드, 인용문 발췌 | [DeepSeek 웹 검색](backend/docs/CONFIGURATION.md#deepseek-web-search) |
| Docker, 로컬 개발, 업그레이드, 프로덕션 배포 | [애플리케이션 실행](docs/guide/deployment.md) |
| 샌드박스 모드, 파일 시스템, 업로드 및 출력 | [샌드박스](docs/guide/sandbox.md) |
| boxd 머신, 출력 복사 제한 및 정리 재시도 | [boxd 샌드박스 프로바이더](backend/packages/harness/deerflow/community/boxd_sandbox/README.md) |
| 스킬, 내장 도구, 스크립트 워크플로, Claude Code 통합 | [스킬과 도구](docs/guide/skills-and-tools.md) |
| MCP 서버 | [MCP 서버](docs/guide/mcp.md) |
| 서브에이전트, 작업 위임 및 선택적 SQLite 체크포인트 기록 | [서브에이전트](docs/guide/subagents.md), [도구 제한](docs/guide/subagents.md#tool-restrictions) |
| 장기 메모리 | [장기 메모리](docs/guide/memory.md) |
| 세션 목표, 컨텍스트 압축, 작업 노트, 근거 기반 의사 결정 | [컨텍스트, 목표 및 에이전트 의사 결정](docs/guide/context.md) |
| 비공개 지식 검색 (RAGFlow) | [비공개 지식 검색](docs/guide/knowledge-retrieval.md) |
| 에이전트 브라우저 제어 | [에이전트 브라우저 제어](docs/guide/browser-control.md) |
| 프로젝트, 지침, 문서 서가 | [프로젝트](docs/guide/projects.md) |
| 예약 작업 | [예약 작업](docs/guide/scheduled-tasks.md) |
| Feishu, Slack, Telegram, Discord, DingTalk 및 기타 IM 채널 | [IM 채널](docs/guide/im-channels.md) |
| 파일 첨부, 다운로드 및 Office 미리보기 | [파일 미리보기](docs/guide/file-previews.md) |
| 토큰 사용량 대시보드, 워크스페이스, 채팅 보관함 | [워크스페이스 UI](docs/guide/workspace.md) |
| 터미널 워크벤치 | [터미널 워크벤치 (TUI)](docs/guide/tui.md) |
| 개인 액세스 토큰, 스트림 동작, 임베디드 Python 클라이언트 | [API 액세스와 Python 클라이언트](docs/guide/api-and-client.md) |
| 트레이스 상관관계, LangSmith, Langfuse, Monocle | [트레이싱과 관측성](docs/guide/observability.md) |
| 배포 위험, 관리자 권한 모델, 보안 권장 사항 | [보안 고지](docs/guide/security.md) |

## 권장 모델

DeerFlow는 특정 모델에 종속되지 않으며, OpenAI 호환 API를 구현하는 모든 LLM과 함께 동작합니다. 다만 다음을 지원하는 모델에서 가장 좋은 성능을 냅니다.

- 심층 리서치와 다단계 작업을 위한 **긴 컨텍스트 윈도우**(100k+ 토큰)
- 적응형 계획과 복잡한 문제 분해를 위한 **추론 능력**
- 이미지 이해와 동영상 이해를 위한 **멀티모달 입력**
- 안정적인 함수 호출과 구조화된 출력을 위한 **강력한 도구 사용 능력**

## 추가 문서

- [Install.md](Install.md) - 코딩 에이전트용 설정 지침
- [설정 레퍼런스](backend/docs/CONFIGURATION.md) - 모든 `config.yaml` 옵션
- [백엔드 아키텍처](backend/README.md) - 백엔드 아키텍처 및 API 레퍼런스
- [대화 공유](docs/guide/sharing.md) - 유효 기간이 있는 읽기 전용 스냅샷, 아티팩트 미리보기 및 워크스페이스로 복사
- [아키텍처 개요](docs/ARCHITECTURE.md) - 서비스 구성 및 연결 방식
- [기여 가이드](CONTRIBUTING.md) - 개발 환경, 워크플로 및 테스트
- [변경 이력](CHANGELOG.md) - 릴리스 노트

## ⚠️ 보안 고지

DeerFlow는 명령을 실행하고 파일을 읽고 쓸 수 있습니다. 로컬의 신뢰할 수 있는 환경에서
실행하도록 설계되었으며, Gateway 관리자 계정에는 호스트에서 코드를 실행하는 것과
동등한 권한이 있습니다. 서버에 배포하거나 네트워크에 공개하기 전에
[보안 고지](docs/guide/security.md) 전문과 [SECURITY.md](SECURITY.md)를 읽어 주세요.

## 기여하기

기여를 환영합니다! 개발 환경 설정, 워크플로, 가이드라인은 [CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요.

## 라이선스

이 프로젝트는 오픈 소스이며 [MIT 라이선스](LICENSE)로 제공됩니다.

## 감사의 말

DeerFlow는 오픈 소스 커뮤니티의 놀라운 성과 위에 만들어졌습니다. DeerFlow를 가능하게 해 준 모든 프로젝트와 기여자의 노력에 깊이 감사드립니다. 우리는 진정으로 거인의 어깨 위에 서 있습니다.

다음 프로젝트들의 소중한 기여에 진심으로 감사드립니다:

- **[LangChain](https://github.com/langchain-ai/langchain)**: 뛰어난 프레임워크로 LLM 상호작용과 체인을 구동하여 매끄러운 통합과 기능을 가능하게 합니다.
- **[LangGraph](https://github.com/langchain-ai/langgraph)**: 멀티 에이전트 오케스트레이션에 대한 혁신적인 접근 방식으로 DeerFlow의 정교한 워크플로를 구현하는 데 핵심적인 역할을 했습니다.

이 프로젝트들은 오픈 소스 협업이 지닌 변혁의 힘을 잘 보여주며, 우리는 그 기반 위에 DeerFlow를 만들 수 있음을 자랑스럽게 생각합니다.

### 주요 기여자

비전과 열정, 헌신으로 이 프로젝트에 생명을 불어넣은 `DeerFlow`의 핵심 저자들에게 진심으로 감사드립니다:

- **[Daniel Walnut](https://github.com/hetaoBackend/)**
- **[Henry Li](https://github.com/magiccube/)**

여러분의 변함없는 헌신과 전문성은 DeerFlow 성공의 원동력이었습니다. 이 여정의 선두에 여러분이 있어 영광입니다.

## Star History

[![Star History Chart](https://star-history.dera.page/svg?repos=bytedance/deer-flow&type=Date)](https://star-history.dera.page/#bytedance/deer-flow&Date)
