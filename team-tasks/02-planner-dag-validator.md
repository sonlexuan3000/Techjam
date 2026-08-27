# Task 02 — Planner Service và DAG Validator

- **Owner:** `@tlam0806`
- **Status:** Ready for review
- **Suggested branch:** `feat/task-02-planner-dag-validator`
- **Reviewer:** `@sonlexuan3000`

**Shared contract:** [Coordination MVP Contracts v1](./CONTRACTS.md)

## Mục tiêu

Biến user prompt thành một dependency graph có schema rõ ràng bằng Planner Agent,
sau đó coi output model là dữ liệu không tin cậy và validate hoàn toàn ở backend.

Planner được gọi qua Agent execution interface của Starter Kit. Không gọi ModelArk
SDK hoặc external AI service trực tiếp.

## Files sở hữu chính

```text
apps/server/src/planner-service.ts
apps/server/src/coordination-prompts.ts
apps/server/src/coordination-graph.ts
apps/server/src/coordination-graph.test.ts
apps/server/src/planner-service.test.ts
```

## Planner output contract

```json
{
  "version": 1,
  "summary": "Short plan summary",
  "tasks": [
    {
      "key": "research-a",
      "title": "Research approach A",
      "instruction": "Analyze benefits, risks and limitations.",
      "dependsOn": [],
      "requiredCapability": "research",
      "expectedOutput": "Concise analysis"
    },
    {
      "key": "synthesis",
      "title": "Produce recommendation",
      "instruction": "Compare the dependency results.",
      "dependsOn": ["research-a"],
      "requiredCapability": "synthesis",
      "expectedOutput": "Final recommendation"
    }
  ],
  "finalTaskKey": "synthesis"
}
```

Planner chỉ đề xuất graph. Planner không được quyết định Agent ID, attempt,
timeout, retry policy hoặc task status.

## Checklist implementation

- [x] Build Planner prompt từ original user goal.
- [x] Đưa allowed capabilities và `request.maxTasks` vào prompt (default policy
  hiện tại là 6; không hard-code trong validator).
- [x] Yêu cầu JSON only, không Markdown.
- [x] Strip một JSON Markdown fence nếu model vẫn trả fence.
- [x] Parse bằng `JSON.parse`.
- [x] Validate shape/length bằng Zod.
- [x] Reject duplicate task key.
- [x] Reject missing dependency.
- [x] Reject self-dependency.
- [x] Detect cycle bằng deterministic graph algorithm.
- [x] Reject graph vượt quá `request.maxTasks`.
- [x] Reject capability không nằm trong allowed capabilities.
- [x] Reject capability không có worker nào đáp ứng.
- [x] Validate `finalTaskKey` tồn tại.
- [x] Bắt buộc reject nếu có task không nằm trên path dẫn tới final task.
- [x] Không tự âm thầm sửa graph lỗi.
- [x] Trả validation error đủ rõ để lưu vào event/UI nhưng không lộ secret.
- [x] Planner admission/runtime failure trả typed failure để core emit
  `plan_failed`; Planner timeout trả typed failure để emit `plan_timed_out`.
- [x] Dùng `request.timeoutMs` và best-effort cancel đúng Planner AgentRun khi
  timeout.
- [x] Sau admission, await `request.registerAgentRun(run.id)`; nếu parent đã
  stop thì cancel Run và không parse/commit Planner output.
- [x] Không retry Planner trong MVP.

## Planner service boundary

Implement đúng `PlannerService` trong shared contract và gọi đúng
`AgentExecutionGateway` của Task 03. Không tạo `PlannerExecutionGateway` riêng:

```ts
interface PlannerService {
  createPlan(request: PlannerRequest): Promise<PlannerResult>;
}
```

Tests inject fake `AgentExecutionGateway` trả discriminated
`AgentStartResult`; success handle hoàn tất bằng AgentRun có output string.

## Automated tests

- [x] Valid DAG parse thành công.
- [x] Markdown-fenced JSON được parse.
- [x] Text không phải JSON bị reject.
- [x] Duplicate key bị reject.
- [x] Missing dependency bị reject.
- [x] Self-dependency bị reject.
- [x] Cycle hai node và nhiều node bị reject.
- [x] Graph quá lớn bị reject.
- [x] Orphan task không dẫn tới final task bị reject.
- [x] Unknown capability bị reject.
- [x] Missing final task bị reject.
- [x] Planner failure không tạo task nửa chừng.
- [x] Planner timeout không tạo task nửa chừng.
- [x] Stop/admission race làm registration trả false và Planner Run bị cancel.
- [x] Busy/not-configured Gateway result map thành typed `plan_failed`.

## Definition of Done

- Cùng một JSON input luôn cho cùng validation result.
- Planner output không thể bypass backend validator.
- Module không biết hoặc chọn Worker Agent ID.
- Có tests cho positive và negative cases.
- `npm run check` pass.

## Ngoài scope

- Plan repair bằng một AI call thứ hai.
- Adaptive replanning.
- Planner tự assign Agent.
- Dynamic model selection.
