# Handoff kỹ thuật cho team slide, video và Devpost

Ngôn ngữ: [English](TEAM_HANDOFF_EN.md) · **Tiếng Việt**

Tài liệu này là bản giải thích tiếng Việt, dùng chung cho những người không trực
tiếp viết backend nhưng cần trình bày InverseCart chính xác. Nếu một con số hoặc
claim trong slide/video khác tài liệu này, ưu tiên kiểm tra lại
[`final_results.json`](final_results.json), [`EVALUATION.md`](EVALUATION.md) và
code production trước khi công bố.

## 1. Bản tóm tắt 30 giây

**Tên sản phẩm:** InverseCart  
**Track:** TikTok TechJam 2026, Track 4 — Shopping Copilot

Một câu nên dùng xuyên suốt:

> InverseCart đảo ngược customer simulator: mỗi sản phẩm trở thành một giả
> thuyết về cuộc hội thoại, rồi một bộ lập kế hoạch theo điểm quyết định nên trả
> bao nhiêu sản phẩm ngay bây giờ hay chờ thêm một câu trả lời.

Điểm kỹ thuật nổi bật:

- Không search lại độc lập ở từng turn. Bot duy trì một tập giả thuyết sản phẩm
  xuyên suốt hội thoại.
- Không cố định Top 10. Bot dùng finite-horizon dynamic programming (DP) để chọn
  số sản phẩm nên trả ở trạng thái hiện tại.
- Không biến mọi dự đoán NLP thành hard filter. Khi không chắc, bot ưu tiên một
  `focus tier` nhưng vẫn giữ `recovery universe` để target có thể quay lại.
- Popularity prior chỉ thay đổi thứ tự và xác suất trong tập hợp lệ; nó không thể
  vượt qua hard constraint.
- Competition runtime chạy offline bằng Python standard library, không cần LLM,
  API key, GPU, vector database hay network request.

Tagline tiếng Anh đã dùng trong Devpost:

> Offline conversational product search with inverse-intent retrieval and
> score-aware recommendation depth.

## 2. Bài toán thật sự cần giải

Evaluator giữ một `parent_asin` bí mật. Agent phải tìm đúng mã đó càng sớm và
càng cao trong danh sách càng tốt. Mỗi session dừng ngay ở lần hit hợp lệ đầu
tiên, nên một target xuất hiện sớm nhưng ở rank thấp không thể được “sửa rank” ở
turn sau.

Các metric được phát hành:

```text
HitRate@10 = số session hit / N
MRR        = trung bình 1 / first-hit rank; miss nhận 0
MTTC       = trung bình first-hit turn; miss được gán turn 11
Efficiency = clip((11 - MTTC) / 10, 0, 1)

TechnicalScore = 0.50 × HitRate@10 + 0.30 × MRR + 0.20 × Efficiency
```

Với một hit tại turn `t`, rank `r`, phần đóng góp theo session là:

```text
reward(t, r) = 0.50 + 0.30 / r + 0.02 × (11 - t)
```

Do đó:

- trả nhiều sản phẩm ngay giúp coverage nhưng có thể khóa MRR ở rank thấp;
- trả quá ít có thể bỏ lỡ target và tốn thêm turn;
- hỏi quá lâu làm MTTC xấu đi.

Đây là lý do “bao nhiêu sản phẩm nên trả” cũng là một quyết định hội thoại, không
chỉ là format output.

Nguồn: [`competition_specification.md`](competition_specification.md),
[`EVALUATION.md`](EVALUATION.md).

## 3. Evaluator và Agent nhìn thấy gì

### 3.1 Dữ liệu catalog

Catalog đóng băng có 50,000 sản phẩm. Các field participant nhìn thấy là:

- `parent_asin`;
- `title`;
- `features`;
- `description`;
- `price`;
- `categories`;
- `details`;
- `average_rating`;
- `rating_number`;
- `store`.

Chỉ exact `parent_asin` được chấm.

### 3.2 Profile đầu session

Evaluator gọi:

```python
agent.reset(session_id, user_profile)
```

Profile an toàn có các dạng field như:

- `purchase_frequency`;
- `average_prior_rating`;
- `rating_style`;
- `preference_tags`;
- `summary`.

Production Agent hiện lưu profile theo session nhưng **không dùng profile để
ranking**, vì team chưa có một cải thiện personalization đủ an toàn và tái lập.
Không được nói trong video rằng kết quả hiện tại đến từ personalization.

### 3.3 Vòng lặp một session

1. Evaluator tạo `session_id`, giữ target và hidden intent card ở phía evaluator.
2. Evaluator gọi `reset(session_id, user_profile)`.
3. Simulated customer gửi một câu theo scenario.
4. Agent chỉ nhận `session_id`, `user_message`, `turn`, `top_k`.
5. Agent trả natural-language `message`, structured `ask_attribute` và ranked
   `recommendations`.
6. Evaluator chuẩn hóa output và chỉ chấm tối đa 10 `parent_asin` hợp lệ, không
   trùng nhau.
7. Nếu chưa hit, evaluator tạo câu trả lời tiếp theo. Nếu hit, session dừng.
8. Session tối đa 10 turn. Với Intent Override, recommendation trước khi intent
   mới xuất hiện không được score.

Scenario mix được phát hành:

- 40% Buying;
- 40% Browsing;
- 15% Intent Override;
- 5% Boundary.

Nguồn: [`competition_specification.md`](competition_specification.md),
[`local_evaluator.py`](../evaluator/local_evaluator.py).

## 4. Full flow low-level của production Agent

Production entrypoint là [`submission/agent.py`](../submission/agent.py). Core
logic nằm trong
[`submission/src/shopping_copilot/core.py`](../submission/src/shopping_copilot/core.py).

### Bước A — Dựng index một lần khi startup

Agent đọc catalog đúng một pass và dựng một `ProductIntent` cho mỗi sản phẩm:

```text
parent_asin
coarse category
up to 2 hard constraints
up to 2 soft preferences
searchable metadata text
rating_number
average_rating
prior weight
```

Intent card được dựng giống participant-visible evaluator:

1. lấy `features` và `details`;
2. chèn material/color được phát hiện từ metadata nếu có;
3. thêm budget từ price nếu có;
4. bỏ trùng;
5. hai value đầu là hard;
6. hai value tiếp là soft; với card quá thưa có fallback về value đầu.

Agent đồng thời dựng category index, initial-message index, exact constraint
index và các lookup nhỏ phục vụ parser. Release audit đã so toàn bộ 50,000 sản
phẩm với evaluator và ghi nhận 0 card/category mismatch.

### Bước B — Parse và canonicalize message

Parser dependency-free nhận biết các nhóm:

- category/browsing mở đầu;
- hard requirement;
- preference;
- reply tiết lộ một hoặc hai value;
- no-preference/boundary;
- negation;
- intent override.

Parser giữ lại span value gốc để những catalog value chứa dấu câu hoặc dấu chấm
phẩy không bị phá hỏng.

### Bước C — Xác định mức độ tin cậy

Một message chỉ đi exact path khi:

- wrapper thuộc released protocol; và
- mọi value được tiết lộ đều ground được vào index catalog.

Nếu không đạt cả hai điều kiện, session chuyển sang NLP fallback. Quyết định này
monotonic trong session: đã có evidence không chắc thì transcript không tự nhiên
được nâng trở lại thành exact-trusted chỉ vì turn sau nhìn giống canonical.

### Bước D — Cập nhật state

State giữ:

- raw và canonical messages;
- initial/current candidates;
- trusted universe;
- focus candidates;
- scenario;
- override state;
- NLP-fallback flag;
- sản phẩm đã bị reject;
- recommendation trước override và recommendation ở turn trước.

Nếu evaluator gọi thêm một turn, recommendation của turn scoreable trước đó chắc
chắn là miss và được đưa vào `rejected`.

Riêng Intent Override:

- recommendation trước override là provisional, chưa được score;
- khi override xuất hiện, các provisional rejection được phục hồi;
- recommendation đã miss thật ở turn scoreable sau đó không được phục hồi nhầm.

Tracker xem `material`, `color`, `size`, `budget` là các slot có thể xung đột rõ.
Khi cùng slot đổi value, value cũ bị supersede. Generic feature có thể cùng tồn
tại nếu không bị phủ định trực tiếp.

### Bước E — Suy ra candidate

**Exact trusted path:** giữ các product card có thể tạo ra đúng transcript đã
quan sát, bao gồm scenario, thứ tự reply `other`, disclosed values và override
timing.

Nếu full hard-plus-soft intersection rỗng, Agent chỉ relax soft suffix. Hard
constraint đã quan sát và genuine rejected products vẫn bắt buộc bị loại.

**Uncertain NLP path:** tách hai lớp:

- `focus tier`: sản phẩm phù hợp nhất với parse hiện tại, được rank và thử trước;
- `recovery universe`: tập eligibility an toàn gần nhất, hoặc toàn catalog nếu
  uncertainty xuất hiện từ turn đầu.

Một parse không chắc có thể đổi thứ tự ưu tiên nhưng không được âm thầm định
nghĩa lại eligibility. Khi focus cạn, target có thể quay lại từ recovery.

### Bước F — Xếp thứ tự candidate

Production belief weight:

```text
w(product) = verified_reviews_365d(product) + 1
```

Trong exact/focus path, thứ tự ổn định lần lượt dùng:

1. smoothed review weight;
2. catalog `rating_number`;
3. `average_rating`;
4. `parent_asin`.

`+1` giữ sản phẩm không có review quan sát được vẫn có xác suất dương. Prior
không thể thêm lại sản phẩm vi phạm hard constraint.

### Bước G — DP chọn recommendation depth

Mỗi hypothesis DP là:

```text
(parent_asin, disclosed_constraint_mask)
```

Với từng `k` từ 1 đến requested Top-K cap, DP cộng:

- expected reward nếu target nằm ở rank `1..k` ngay turn này;
- miss branch sau khi prefix đó bị reject;
- mọi reply `other` mà các product card còn lại có thể sinh;
- future value đến hết turn 10.

Những sản phẩm tạo cùng reply `other` nằm trong cùng một branch. Branch
probability là tổng prior weight của các sản phẩm trong branch. Trên turn vague
đầu tiên, recurrence còn mô hình hóa released Browsing/Boundary mixture.

DP chọn **độ dài prefix**, không đổi permutation và không chọn question type.

Nếu NLP fallback không còn focus đáng tin, Agent không áp DP lên một ranking yếu.
Nó dùng schedule bảo thủ:

- turn 1: tối đa 1 sản phẩm;
- turn 2: tối đa 2 sản phẩm;
- turn 3 trở đi: tối đa 10 sản phẩm.

### Bước H — Trả output

Production luôn trả:

```python
{
    "message": "Which two product details matter most to you?",
    "ask_attribute": "other",
    "recommendations": [{"parent_asin": "..."}],
    "usage": {"prompt_tokens": 0, "completion_tokens": 0},
}
```

`other` được chọn vì released simulator có thể tiết lộ tối đa hai value còn lại
từ toàn card. Nó tạo partition giàu thông tin hơn named attribute khi metadata
field thưa hoặc không nhất quán.

Nguồn chi tiết: [`ARCHITECTURE.md`](ARCHITECTURE.md),
[`submission/README.md`](../submission/README.md).

## 5. Vì sao hit đúng ngay turn 1 vẫn có thể hợp lệ

Turn-1 hit không tự động có nghĩa là bot đọc ground truth.

1. Released first message được sinh deterministically từ target card.
2. Agent dựng cùng loại card cho toàn catalog từ metadata participant được xem.
3. Một câu category + exact requirement có thể chỉ khớp một tập rất nhỏ.
4. Trong tập đó, review prior có thể xếp target ở rank 1.
5. Agent không nhận `ground_truth`, hidden card hoặc target flag qua interface.

Ví dụ mặc định `public_0001`: opening message exact chỉ còn **2** hypothesis.
Target `B09PYB7B6Z` có review count 365 ngày là `2`, còn competitor có `0`, nên
prior xếp target trước và DP trả K=1. Trên cả public development 200, first-hit
distribution là: turn 1 có 90 session, turn 2 có 71, turn 3 có 20 và turn 4 có
19. Vì vậy turn-1 hit là behavior thường xuyên của backend, không phải case cần
ẩn đi.

Frontend cần target để đóng vai evaluator và tô highlight sau khi chấm. Điều đó
khác với production Agent đọc target. `GET /api/sessions` cố ý bỏ ground truth và
hidden intent; `POST /api/simulate` chỉ gọi Agent qua contract bình thường.

Khi quay video, nên đặt caption:

> Ground-truth highlighting is evaluator-side visualization only. The Agent
> receives only profile, message, turn, and Top-K.

Giữ nguyên default behavior của frontend. Khi ghi hình, chọn thủ công
`public_0120` để đáp ứng yêu cầu demo một full multi-turn session và cho thấy
candidate narrowing; nếu show `public_0001`, giải thích pool hai hypothesis như
trên.

## 6. Ranh giới data và leakage

### Runtime thực sự đọc gì

- organizer catalog;
- conversation inputs theo Agent contract;
- `submission/data/review_prior.tsv`.

Prior có đúng một aggregate count cho mỗi một trong 50,000 catalog ASIN. Có
5,777 sản phẩm có count khác 0; smoothing cho phần còn lại weight bằng 1.

Prior **không chứa**:

- `sample_id`;
- user/profile mapping;
- review text;
- user identifier;
- timestamp từng review;
- individual review row;
- public-session mapping;
- target flag;
- unreleased organizer label.

Count là số verified review trong cửa sổ 365 ngày trước exclusive cutoff
`2023-10-01`, được aggregate từ Amazon Reviews 2023
`Clothing_Shoes_and_Jewelry` và join bằng `parent_asin`.

### Điều được phép claim

- Không có unreleased/session-label leakage trong runtime asset.
- Agent không load public-set target mapping.
- Final prior type được chọn trên organizer-labeled public development set và
  việc này được công khai.
- Không final-evaluation session hoặc unreleased label nào có sẵn hay được dùng.

### Điều không được claim

Không nói prior “hoàn toàn leakage-free theo thời gian”. Aggregate quét disclosed
source trước cutoff và có thể chứa event thuộc giai đoạn organizer sau đó xem là
held out. Đây là predictive popularity prior, không phải causal estimate hay
temporal-leakage-free evaluation.

Algorithm được chọn trên generated development. Review prior cuối được chọn trên
public development sau khi team xác nhận external data được phép. Generated
holdout được giữ như một distribution/regression check và cho kết quả ngược với
public; nó không phải hidden/private set.

Nguồn: [`DATA_ATTRIBUTION.md`](../DATA_ATTRIBUTION.md),
[`DEVELOPMENT_PROVENANCE.md`](DEVELOPMENT_PROVENANCE.md),
[`submission/data/README.md`](../submission/data/README.md).

## 7. Kết quả và ablation đã kiểm chứng

### Organizer public development

| Backend | Sessions | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|---:|
| Released weak BM25 | 200 | 0.1250 | 0.068034 | 9.8100 | 0.106710 |
| Uniform inverse-DP | 200 | 1.0000 | 0.997500 | 2.7950 | 0.963350 |
| Catalog `rating_number` inverse-DP | 200 | 1.0000 | 1.000000 | 2.0050 | 0.979900 |
| **Review-prior inverse-DP — shipped** | **200** | **1.0000** | **1.000000** | **1.8400** | **0.983200** |

So với uniform core giống hệt, review prior đưa target tới turn sớm hơn trong
117 session, giữ nguyên 82 session và muộn hơn trong 1 session. Public Technical
Score tăng `+0.019850`.

### Generated development dùng để chọn algorithm

| Backend | Sessions | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|---:|
| Previous exact-evidence backend | 2,000 | 0.9865 | 0.852769 | 2.7010 | 0.915061 |
| Uniform inverse-DP | 2,000 | 0.9935 | 0.977300 | 2.6255 | 0.957430 |
| Catalog `rating_number` prior | 2,000 | 0.9935 | 0.974768 | 2.6890 | 0.955400 |
| **Review prior — shipped** | **2,000** | **0.9945** | **0.978687** | **2.6200** | **0.958456** |

Review prior chỉ tăng `+0.001026` so với uniform trên split này. Phần tăng lớn
từ backend cũ lên final đến từ inverse hypothesis filtering và DP, không phải
chỉ từ popularity.

### Generated holdout distribution check

| Prior | Sessions | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|---:|
| Uniform | 800 | 0.9975 | 0.980420 | 2.5850 | 0.961176 |
| **Review prior — shipped** | **800** | **0.9925** | **0.976574** | **2.5950** | **0.957322** |

Review prior giảm `-0.003854` trên fixture sample target gần uniform. Phải công
khai kết quả trái chiều này; nó cho thấy prior phụ thuộc target distribution.

### Public scenario breakdown của final backend

| Scenario | Sessions | HR@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| Buying | 80 | 1.0000 | 1.000000 | 1.3375 |
| Browsing | 80 | 1.0000 | 1.000000 | 1.6625 |
| Intent Override | 30 | 1.0000 | 1.000000 | 3.6000 |
| Boundary | 10 | 1.0000 | 1.000000 | 2.0000 |

Intent Override có MTTC cao hơn phần lớn vì target không được phép convert trước
khi replacement intent xuất hiện ở turn 3 hoặc 4.

### NLP robustness boundary

- Đổi wrapper nhưng giữ exact catalog value: cùng score `0.958456`, có
  `0/2,000` scored-session summary khác nhau.
- Independent 100-case diagnostic:

| Diagnostic | Passed |
|---|---:|
| Exact-value wrapper grounding | 42 / 52 |
| Semantic-value grounding | 1 / 35 |
| Complete state plus grounding | 1 / 100 |

Không được dùng các số wrapper để claim arbitrary semantic understanding.

### Runtime và test

Đo trên Apple M4 với catalog 50,000 sản phẩm:

- startup `6.4312 s`;
- Agent startup RSS increment `194.80 MiB`;
- `17.527 ms` mean và `74.693 ms` p95 trên 368 response calls;
- runtime prompt/completion token `0 / 0`;
- marginal runtime model cost `$0`.

`make test` hiện chạy 54 shared state/parser/contract/frontend tests và 21
selected inverse-DP tests, tổng cộng **75 passing**. Con số runtime là
measurement trên một máy,
không phải service-level guarantee.

Nguồn số liệu: [`final_results.json`](final_results.json),
[`baseline_results.json`](baseline_results.json), [`EVALUATION.md`](EVALUATION.md),
[`Makefile`](../Makefile).

## 8. Session nên dùng để quay demo

Chạy:

```bash
make setup
make frontend
```

Mở <http://localhost:8787>. Giữ nguyên default behavior của frontend; dùng ô tìm
kiếm/session picker để chọn session cần quay.

### Primary: `public_0120`

- Scenario: Browsing, difficulty medium.
- Category: Card Cases & Money Organizers / Wallets.
- Target: `B08GPGX2QG`, SENDEFN women's leather wallet.
- Kết quả production: hit turn 3, rank 1.

Conversation deterministic:

1. User đang tìm wallet nhưng vẫn exploring.
2. Sau câu hỏi `other`, user tiết lộ `leather` và `color: red`.
3. Sau câu hỏi tiếp theo, user tiết lộ `Leather lining` và `Snap closure`; target
   lên rank 1.

Lý do chọn: đủ multi-turn để thấy candidate narrowing, constraint accumulation
và hỏi `other`, nhưng không quá dài cho video.

### Backup: `public_0080`

- Intent Override, difficulty hard.
- Target `B0BPRQY4CF`, IZOD men's polo.
- Hit hợp lệ turn 4, rank 1.
- Dùng khi cần minh họa target có thể xuất hiện trong recommendation trước
  override nhưng evaluator chưa được phép tính hit.

### Backup: `public_0112`

- Boundary, difficulty medium.
- Target `B086ZNJY8K`, Nautica men's walking sneaker.
- User trả no-preference một lần rồi tiết lộ `leather`/`Leather sole`.
- Hit turn 3, rank 1.

## 9. Outline tám slide

### Slide 1 — Title và hook

- InverseCart.
- “Search for the product that could have generated the conversation.”
- Offline, deterministic, score-aware conversational retrieval.

### Slide 2 — Tại sao bài toán không phải Top-10 search thường

- Hit Rate cần coverage.
- MRR cần rank cao.
- MTTC cần ít turn.
- First hit kết thúc session, nên phải quyết định recommend-now hay clarify.

### Slide 3 — Core insight: product as hypothesis

- Một product metadata row được dựng thành intent card.
- Mỗi card dự đoán nó sẽ tạo ra initial message và reply `other` nào.
- Transcript loại dần hypothesis không thể giải thích hội thoại.

### Slide 4 — Architecture

Visual flow:

```text
Catalog + review aggregate
        ↓
Intent cards + indexes
        ↓
Message parser → session state
        ↓
Exact candidates hoặc focus + recovery
        ↓
Fixed candidate ordering
        ↓
Finite-horizon Top-K policy
        ↓
Recommendations + other
```

### Slide 5 — DP chọn K như thế nào

- Thử mọi `k` từ 1 tới Top-K cap.
- Cân immediate rank reward với expected value của reply tiếp theo.
- Cùng reply tạo cùng DP branch.
- DP chọn prefix length, không chọn permutation hay question type.

### Slide 6 — NLP safety và Intent Override

- Exact grounded evidence có thể lọc eligibility.
- Uncertain evidence chỉ tạo focus, recovery vẫn giữ.
- Same-slot override supersede value cũ.
- Provisional pre-override recommendations được phục hồi đúng timing.

### Slide 7 — Results và ablation

Chart chính nên dùng bốn public Technical Score:

```text
Weak BM25             0.106710
Uniform inverse-DP    0.963350
rating_number prior   0.979900
Review prior shipped  0.983200
```

Caption trung thực: public set dùng chọn final prior; generated holdout giảm
`0.003854` so với uniform.

### Slide 8 — Ship-ready và giới hạn

- Python standard library, offline, zero model tokens/API cost.
- 75 tests hiện tại.
- Reproducible archive và data provenance.
- Weakness lớn nhất: semantic-value paraphrase.
- Public/generated results không dự đoán final-evaluation score.

## 10. Recommended cut cho video ba phút

Đây là gợi ý dựng nội bộ, **không phải thêm một rule của organizer**.

| Time | Nội dung | Hình ảnh |
|---|---|---|
| 0:00–0:15 | Hook | Title + one-line idea |
| 0:15–0:35 | Metric conflict | Hit Rate/MRR/MTTC triangle |
| 0:35–1:20 | Live `public_0120` | Viewer ở Step mode, ba turn |
| 1:20–2:05 | Architecture | Highlight product hypothesis, focus/recovery, DP |
| 2:05–2:40 | Metrics | Public ablation + honest holdout caption |
| 2:40–3:00 | Practicality và close | Offline, zero tokens, limitation |

Video cần ít nhất một demonstrated multi-turn session theo repository technical
specification. Event-level video format, URL visibility và deadline vẫn phải
kiểm tra trên official Devpost page.

Script narration ngắn:

> Normal search ranks products independently. InverseCart asks a different
> question: which product could have generated everything the customer has said
> so far? Each remaining product predicts the next clarification. A
> finite-horizon planner then chooses how many results to expose now, balancing
> coverage, reciprocal rank and turn efficiency. When language is uncertain, a
> recovery universe prevents a parser guess from deleting the target. The final
> runtime is deterministic, offline and uses zero model tokens.

Chi tiết quay dựng nằm trong
[`VIDEO_TECHNICAL_NOTES.md`](VIDEO_TECHNICAL_NOTES.md).

## 11. Checklist Devpost/document

### Nội dung bắt buộc phải nhất quán

- Project title: InverseCart.
- Tagline và short description.
- Problem/inspiration.
- What it does.
- Năm lớp kỹ thuật: intent cards, parser/state, recovery, DP, prior.
- Models/APIs/cost disclosure.
- Public result được gọi là labeled development, không phải private/final score.
- Generated development/holdout purpose và target distribution caveat.
- Known limitations.
- Setup/test commands.
- Repository URL và public video URL trong đúng Devpost fields.

### Trước khi paste

- Dùng [`DEVPOST_SUBMISSION.md`](DEVPOST_SUBMISSION.md) làm bản nguồn.
- Test count release phải là 75: 54 shared + 21 inverse-DP.
- Không thêm adaptive-K experiment vào shipped method; production vẫn là
  review-prior inverse-DP.
- Nếu nhắc viewer, gọi nó là local visualization/demo tool, không phải scoring
  runtime.
- Kiểm tra repository visibility và video visibility theo official Devpost.

## 12. Judge Q&A

### “Sao bot biết đúng ngay turn 1, có đọc đáp án không?”

Không. Initial message được simulator sinh deterministically từ target metadata;
Agent dựng cùng loại intent card cho toàn catalog nên câu exact có thể thu hẹp về
một tập rất nhỏ. Popularity prior xếp thứ tự trong tập đó. Ground truth chỉ ở
evaluator/frontend scoring layer, không được truyền vào `Agent.respond`.

### “Prior có hardcode public 200 không?”

Không có session mapping hoặc target label trong TSV. Mỗi row chỉ là
`parent_asin` và aggregate verified-review count. Tuy nhiên team đã thử các prior
và chọn final review prior trên public development 200; điều này được disclosure
rõ và không được mô tả như blind test.

### “External review data có leakage không?”

Không có unreleased/session-label leakage. Nhưng team không claim temporal
leakage-free vì source aggregate có thể overlap với giai đoạn organizer coi là
held out. Đây là predictive prior, không phải causal estimate.

### “Điểm tăng đến từ review prior hay thuật toán?”

Public weak BM25 là `0.106710`, uniform inverse-DP đã là `0.963350`; final review
prior là `0.983200`. Vì vậy phần cải thiện chính đến từ inverse hypothesis
inference và recommendation-depth planning. Prior là lớp belief bổ sung.

### “Tại sao luôn hỏi `other`?”

Released simulator cho `other` tiết lộ tối đa hai value còn lại trên toàn card.
Điều đó tạo candidate partition mạnh và dễ dự đoán hơn named attributes khi
metadata sparse hoặc inconsistent.

### “DP có chọn câu hỏi hoặc rerank không?”

Không. DP chọn `k` cho fixed ordering. Structured question của final backend luôn
là `other`.

### “Hard và soft khác nhau thế nào?”

Hard evidence đã quan sát vẫn bắt buộc. Nếu full hard+soft match rỗng, Agent có
thể relax soft nhưng không phục hồi hard mismatch hoặc genuine miss.

### “NLP xử lý semantic paraphrase đến đâu?”

Tốt nhất ở wrapper changes giữ exact catalog value. General semantic rewrite
vẫn yếu: diagnostic chỉ ground `1/35`. Focus/recovery hạn chế false elimination,
không biến câu chưa hiểu thành semantic match đúng.

### “Có dùng profile không?”

Profile được lưu để đúng session contract nhưng chưa dùng ranking vì chưa chứng
minh được gain an toàn và tái lập.

### “Có cần LLM/API/GPU không?”

Không. Runtime dùng Python standard library, offline, zero runtime model calls,
tokens và marginal model cost.

### “Frontend có nằm trong submission scoring không?”

Không. Frontend là viewer local. Archive builder chỉ đóng gói thư mục
`submission/` và compact prior cần cho Agent.

### “Có thể đảm bảo final score bằng public không?”

Không. Public 200 đã được dùng để chọn prior, generated data dùng released
simulator assumptions, và prior còn regression trên generated holdout. Mọi số
đều là development evidence.

### “Agent có thread-safe không?”

Một Agent instance hỗ trợ nhiều session tuần tự qua `session_id`. Concurrent
calls cần external lock; local viewer đã serialize simulation access.

## 13. Claim guardrails

### Có thể nói

- “100% Hit Rate@10 và MRR 1.0 trên organizer public development 200.”
- “Public Technical Score 0.983200.”
- “Algorithm selected on generated development; final prior selected on public
  development.”
- “Runtime asset contains no public/final-session mapping or unreleased label.”
- “Offline, deterministic, standard-library-only runtime.”
- “Recovery protects eligibility under uncertain parsing.”

### Không được nói

- “Private score là/sẽ là 0.9832.”
- “Bot hiểu mọi paraphrase.”
- “DP tự chọn câu hỏi tốt nhất.”
- “Profile personalization giúp tăng điểm.”
- “Review source hoàn toàn temporal-leakage-free.”
- “Generated 800 holdout là hidden/private test.”
- “Technical Score là toàn bộ final hackathon score.”
- “Adaptive-K experiment mới đang chạy trong submission.”
- “Frontend target badge là evidence Agent được nhìn thấy target.”

## 14. Glossary

| Thuật ngữ | Nghĩa đơn giản |
|---|---|
| `parent_asin` | Mã sản phẩm được evaluator chấm exact match |
| Intent card | Bản tóm tắt category, hard và soft values mà simulator dùng |
| Hard constraint | Điều kiện phải giữ trên trusted path |
| Soft preference | Sở thích có thể relax nếu full intersection rỗng |
| Hypothesis | Một sản phẩm có khả năng giải thích transcript hiện tại |
| Inverse simulator | Suy ngược sản phẩm nào có thể tạo ra hội thoại đã thấy |
| Candidate pool | Tập sản phẩm còn đang được xét |
| Trusted universe | Tập eligibility gần nhất được xác lập bằng evidence đáng tin |
| Focus tier | Candidate được NLP không chắc ưu tiên trước |
| Recovery tier | Candidate an toàn còn lại, dùng khi focus cạn |
| Evidence | Thông tin category/constraint/negation/override lấy từ message |
| Override | Preference cũ bị thay bằng intent/value mới |
| Prior | Trọng số tin tưởng ban đầu trước khi có đủ evidence |
| Smoothing `+1` | Giữ zero-review product có xác suất dương |
| DP | Tính expected future score qua nhiều turn và reply branch |
| `k` | Số recommendation được trả ở turn hiện tại |
| Top-K cap | Giới hạn tối đa evaluator/request cho phép |
| Hit Rate@10 | Tỷ lệ session tìm được target trong scored Top 10 |
| MRR | Trung bình nghịch đảo first-hit rank |
| MTTC | Trung bình first-hit turn; miss tính 11 |
| Efficiency | Điểm biến đổi từ MTTC |
| Public development | 200 labeled sessions do organizer phát hành |
| Generated development | 2,000 session tái lập dùng chọn algorithm |
| Generated holdout | 800 session seed công khai dùng regression check |
| Wrapper paraphrase | Đổi cách nói xung quanh nhưng giữ exact catalog value |
| Semantic paraphrase | Đổi cả value/ý nghĩa bề mặt, ví dụ rain-safe → waterproof |
| Viewer/frontend | UI local mô phỏng evaluator để demo; không phải runtime nộp |

## 15. Source map

| Cần hiểu | File nguồn |
|---|---|
| Landing story và quick start | [`README.md`](../README.md) |
| Production package | [`submission/README.md`](../submission/README.md) |
| Báo cáo self-contained | [`submission/REPORT.md`](../submission/REPORT.md) |
| Architecture/state/DP | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Metrics, ablation, caveats | [`EVALUATION.md`](EVALUATION.md) |
| Machine-readable metrics | [`final_results.json`](final_results.json) |
| Baseline metrics | [`baseline_results.json`](baseline_results.json) |
| Devpost copy | [`DEVPOST_SUBMISSION.md`](DEVPOST_SUBMISSION.md) |
| Video notes | [`VIDEO_TECHNICAL_NOTES.md`](VIDEO_TECHNICAL_NOTES.md) |
| Data provenance | [`DATA_ATTRIBUTION.md`](../DATA_ATTRIBUTION.md) |
| Prior extraction disclosure | [`DEVELOPMENT_PROVENANCE.md`](DEVELOPMENT_PROVENANCE.md) |
| Technical rules | [`competition_specification.md`](competition_specification.md) |
| Package rules | [`submission_rules.md`](submission_rules.md) |
| Final evaluator/code freeze | [`final_evaluation_faq.md`](final_evaluation_faq.md) |
| Checklist nộp bài | [`FINAL_SUBMISSION_CHECKLIST.md`](FINAL_SUBMISSION_CHECKLIST.md) |
| Viewer usage | [`frontend/README.md`](../frontend/README.md) |
| Production entrypoint | [`submission/agent.py`](../submission/agent.py) |
| Core implementation | [`core.py`](../submission/src/shopping_copilot/core.py) |
| Parser/state | [`parser.py`](../submission/src/shopping_copilot/parser.py), [`intent_tracker.py`](../submission/src/shopping_copilot/intent_tracker.py) |

## 16. Release và reproduction commands

Từ repository root:

```bash
# Bootstrap catalog, verify checksum và verify prior coverage
make setup

# 54 shared state/parser/contract/frontend + 21 selected inverse-DP tests
make test

# Public development verification; không dùng như vòng tuning mới
make integration-check

# Tái tạo generated dev + holdout
make unseen-data
make evaluate-unseen-dev
make evaluate-unseen-holdout

# Language diagnostics
make human-stress

# CLI demo và local viewer
make demo
make frontend

# Build deterministic offline runtime ZIP
make submission-archive
```

Sau khi build:

```bash
unzip -l dist/shopping-copilot-submission.zip
shasum -a 256 dist/shopping-copilot-submission.zip
```

Sau khi extract ZIP, smoke test bằng catalog do organizer cung cấp:

```bash
python3 submission/smoke.py --catalog /absolute/path/to/catalog.jsonl
```

Archive chỉ chứa runtime trong `submission/`; catalog, generated datasets,
frontend, raw review rows, Git history, virtualenv và evaluation outputs không
được bundle.

## 17. Final pre-publish check

- [ ] `make test` pass 75 tests.
- [ ] `make integration-check` tái lập public metrics đã ghi.
- [ ] `make submission-archive` thành công.
- [ ] Smoke test archive đã extract.
- [ ] README, report, Devpost và video dùng cùng backend name/result.
- [ ] Mọi test-count claim đều ghi đúng 75 = 54 shared + 21 inverse-DP.
- [ ] Video dùng một session multi-turn; khuyến nghị `public_0120`.
- [ ] Caption giải thích target highlight thuộc evaluator-side.
- [ ] Public result được gọi là development result.
- [ ] Prior selection và holdout regression được disclosure.
- [ ] Không claim arbitrary semantic paraphrase support.
- [ ] Repository và video visibility đáp ứng official Devpost.
