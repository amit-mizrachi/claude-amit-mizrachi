# Subagent delegation

Codex, you are the primary executor. Use specialized agents to improve quality and parallelize work. Match the task to the right agent.

## Architecture & Design
| Agent                  | When to use                                                                                |
| ---------------------- | ------------------------------------------------------------------------------------------ |
| **software-architect** | System design, technology choices, service boundaries, data flows, architectural decisions |
| **Plan**               | Designing implementation strategy before writing code                                      |

## Backend & Frontend
| Agent | When to use |
|-------|-------------|
| **backend-specialist** | API design, database architecture, ORM, auth flows, caching, message queues, microservices |
| **frontend-specialist** | React/Next.js, CSS, accessibility, performance, client-side state management |

## Exploration
| Agent | When to use |
|-------|-------------|
| **Explore** | Finding files, searching code, answering codebase questions (quick/medium/thorough) |
| **general-purpose** | Multi-step research, broad searches, tasks that don't fit other agents |

## Protocol
- Use **Explore** for codebase-wide searches that need more than 3 queries.
