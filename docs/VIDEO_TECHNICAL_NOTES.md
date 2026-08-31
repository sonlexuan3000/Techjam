# Internal technical notes for the demo video

This is a handoff for the teammate producing the public three-minute video. It
is not Devpost description copy.

## Recommended story

1. **Problem, 20 seconds.** A fixed Top 10 improves coverage but can lock in a
   poor reciprocal rank; too much clarification consumes turn efficiency.
2. **Live proof, 60 seconds.** Run `make demo`. The current deterministic demo
   returns one product on turn one, asks `other`, receives two exact constraints,
   and places the hidden target at rank one on turn two.
3. **Technical idea, 60 seconds.** Show the README architecture diagram:
   product-as-hypothesis inference, reversible focus/recovery, then
   finite-horizon selection of the recommendation prefix length.
4. **Evidence, 30 seconds.** Show the final public integration result: HR@10
   `1.0000`, MRR `0.997500`, MTTC `2.7950`, Technical Score `0.963350`.
5. **Practicality and honesty, 10 seconds.** Close on standard-library-only,
   offline inference, zero runtime model tokens, and the explicit semantic-NLP
   limitation.

## Claims to keep precise

- DP chooses recommendation depth for a fixed ordering; it does not choose the
  question type or learn a new ranking permutation.
- The structured question is always `other` in the final backend.
- The 800-session generated regression split has a public seed; do not call it
  hidden or private.
- Wrapper stress preserves exact catalog values; do not claim support for
  arbitrary semantic paraphrases.
- `TechnicalScore` is an objective input to Technical Execution, not the entire
  judged hackathon score.
