# MVP Team Task Board

Thư mục này dùng để chia việc cho MVP **Multi-Agent DAG Coordination Middleware**.
GitHub gọi quy trình review là **Pull Request (PR)**; nó tương đương với Merge
Request trên GitLab.

Leader và người duyệt cuối: **@sonlexuan3000**.

Trước khi bắt đầu code, mọi thành viên phải đọc
[Coordination MVP Contracts v1](./CONTRACTS.md). Đây là source of truth cho API,
types, Planner JSON, module interfaces, statuses và events giữa năm task. Server
ports đã được scaffold tại
[`apps/server/src/coordination-types.ts`](../apps/server/src/coordination-types.ts);
không copy chúng sang một server file khác.

## Scope đã khóa

MVP chỉ gồm:

```text
User prompt
→ Planner Agent qua AgentService/AgentRunner có sẵn
→ Planner đề xuất JSON dependency graph
→ Backend validate graph
→ Ready queue + capability matching
→ Worker Agent execution
→ Attempt + timeout + retry/reassignment
→ currentAttemptId từ chối kết quả cũ
→ UI graph + status + event history
```

Giới hạn mặc định:

```text
maxTasks       = 6
maxParallelism = 2
maxAttempts    = 2
```

Không làm trong MVP: lease, heartbeat, adaptive replanning, Evaluator Agent,
shared filesystem, distributed queue, model routing, ECS và graph editor phức
tạp.

## Chọn task

| Task | Nội dung | Owner | Status |
| --- | --- | --- | --- |
| [Task 01](./01-coordination-core.md) | Coordination core và scheduler | Chưa có | Unassigned |
| [Task 02](./02-planner-dag-validator.md) | Planner service và DAG validator | @tlam0806 | In progress |
| [Task 03](./03-agent-execution-attempt-retry.md) | Agent execution gateway, capabilities và Run correlation | Chưa có | Unassigned |
| [Task 04](./04-coordination-ui.md) | Coordination UI, graph và event timeline | Chưa có | Unassigned |
| [Task 05](./05-api-persistence-testing-demo.md) | API, persistence, integration tests và demo | Chưa có | Unassigned |

Để claim một task mà không bị hai người cùng chọn:

1. Kiểm tra bảng trên và danh sách Pull Request đang mở.
2. Tạo một branch claim từ `main`.
3. Điền GitHub username vào `Owner` và đổi `Status` thành `In progress` ở cả
   bảng trên lẫn file task đã chọn.
4. Mở một PR nhỏ chỉ chứa thay đổi claim task.
5. Chờ leader merge PR claim trước khi bắt đầu branch implementation.

Ví dụ claim Task 02:

```bash
git switch main
git pull --ff-only origin main
git switch -c chore/claim-task-02-<github-username>
```

Sau khi sửa hai file Markdown:

```bash
git add team-tasks/README.md team-tasks/02-planner-dag-validator.md
git commit -m "chore(task-02): claim planner and DAG validator"
git push -u origin chore/claim-task-02-<github-username>
```

Mở Pull Request vào `main` và request review từ `@sonlexuan3000`. Sau khi PR
claim được merge, tạo branch implementation mới từ `main` đã cập nhật.

## Tạo branch implementation

Không code trực tiếp trên `main`.

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/task-02-planner-dag-validator
```

Quy ước branch:

```text
feat/task-01-coordination-core
feat/task-02-planner-dag-validator
feat/task-03-agent-execution
feat/task-04-coordination-ui
feat/task-05-api-persistence-tests
fix/task-XX-short-description
```

Commit message nên nhỏ và mô tả đúng thay đổi:

```text
feat(task-02): validate DAG cycles and dependencies
test(task-01): reject stale attempt completion
fix(task-04): keep event polling after refresh
docs(task-05): document controlled timeout demo
```

## Đồng bộ với `main`

Trước khi mở hoặc cập nhật PR:

```bash
git fetch origin
git merge origin/main
npm run check
git push
```

Nếu có conflict, người sở hữu file phải resolve trên feature branch. Không
resolve conflict trực tiếp trên `main`.

## Mở Pull Request

Push branch:

```bash
git push -u origin <branch-name>
```

Sau đó mở PR trên GitHub với:

- Base branch: `main`.
- Reviewer: `@sonlexuan3000`.
- Draft PR nếu chức năng chưa hoàn thành.
- Chỉ chuyển sang Ready for review khi checklist trong file task đã đạt.

PR description dùng format:

```markdown
## Summary

Mô tả ngắn thay đổi và lý do.

## Scope

- Phần đã làm
- Phần cố ý chưa làm

## Verification

- [ ] Unit/integration tests liên quan đã pass
- [ ] `npm run check` đã pass
- [ ] Baseline Agent CRUD và Playground không bị hỏng
- [ ] Không có secret, `.env` hoặc credential trong diff/log/screenshot

## Evidence

Ảnh, API response hoặc event sequence chứng minh chức năng.

## Risks / limitations

Các giới hạn hoặc việc cần người tích hợp lưu ý.
```

## Quy tắc review và merge

Chỉ `@sonlexuan3000` merge vào `main` sau khi:

1. Scope khớp file task và không thêm feature ngoài MVP.
2. Logic quan trọng có automated tests.
3. `npm run check` pass.
4. Không có API key, `.env`, token, workspace state hoặc generated data.
5. Không làm hỏng single-Agent Playground hiện có.
6. Author đã xử lý toàn bộ review comments.
7. PR đã được đồng bộ với `origin/main`.

Ưu tiên **Squash and merge**, sau đó xóa feature branch. Thành viên cập nhật local:

```bash
git switch main
git pull --ff-only origin main
git branch -d <branch-name>
```

## Thiết lập GitHub cho leader

Trong repository Settings → Branches, tạo protection rule cho `main`:

- Require a pull request before merging.
- Require at least 1 approval.
- Dismiss stale approvals when new commits are pushed.
- Block force pushes.
- Block branch deletion.

Chỉ bật “Require status checks” sau khi repo có GitHub Actions workflow tương
ứng; nếu bật quá sớm, team có thể không merge được PR.

## Thứ tự tích hợp

1. Merge và giữ ổn định [Coordination MVP Contracts v1](./CONTRACTS.md).
2. Merge Planner/DAG validator và Agent execution gateway.
3. Merge Coordination core với hai interface trên.
4. Merge API/persistence.
5. Kết nối UI.
6. Chạy end-to-end ModelArk, timeout/retry demo và toàn bộ validation suite.

Task có thể phát triển song song bằng fake/fixture, nhưng shared contract không
được tự ý đổi. Mọi thay đổi contract phải được leader duyệt trước.
