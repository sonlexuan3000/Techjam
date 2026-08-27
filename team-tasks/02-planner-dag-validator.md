# Task 02 — Planner Service và DAG Validator

- **Owner:** `@tlam0806`
- **Status:** In progress
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

- [ ] Build Planner prompt từ original user goal.
- [ ] Đưa allowed capabilities và `maxTasks = 6` vào prompt.
- [ ] Yêu cầu JSON only, không Markdown.
- [ ] Strip một JSON Markdown fence nếu model vẫn trả fence.
- [ ] Parse bằng `JSON.parse`.
- [ ] Validate shape/length bằng Zod.
- [ ] Reject duplicate task key.
- [ ] Reject missing dependency.
- [ ] Reject self-dependency.
- [ ] Detect cycle bằng deterministic graph algorithm.
- [ ] Reject graph vượt quá sáu task.
- [ ] Reject capability không nằm trong allowed capabilities.
- [ ] Reject capability không có worker nào đáp ứng.
- [ ] Validate `finalTaskKey` tồn tại.
- [ ] Tốt nhất yêu cầu mọi task đều dẫn tới final task.
- [ ] Không tự âm thầm sửa graph lỗi.
- [ ] Trả validation error đủ rõ để lưu vào event/UI nhưng không lộ secret.
- [ ] Planner admission/runtime failure trả typed failure để core emit
  `plan_failed`; Planner timeout trả typed failure để emit `plan_timed_out`.
- [ ] Không retry Planner trong MVP.

## Planner service boundary

Implement đúng `PlannerService` trong shared contract và gọi đúng
`AgentExecutionGateway` của Task 03. Không tạo `PlannerExecutionGateway` riêng:

```ts
interface PlannerService {
  createPlan(request: PlannerRequest): Promise<PlannerResult>;
}
```

Tests inject fake `AgentExecutionGateway` trả AgentRun có output string.

## Automated tests

- [ ] Valid DAG parse thành công.
- [ ] Markdown-fenced JSON được parse.
- [ ] Text không phải JSON bị reject.
- [ ] Duplicate key bị reject.
- [ ] Missing dependency bị reject.
- [ ] Self-dependency bị reject.
- [ ] Cycle hai node và nhiều node bị reject.
- [ ] Graph quá lớn bị reject.
- [ ] Unknown capability bị reject.
- [ ] Missing final task bị reject.
- [ ] Planner failure không tạo task nửa chừng.
- [ ] Planner timeout không tạo task nửa chừng.

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
