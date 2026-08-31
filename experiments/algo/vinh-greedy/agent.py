"""Winning baseline-rank candidate with a frozen conservative Dynamic-K policy."""

from __future__ import annotations

from pathlib import Path

from starter.agent import Agent

from k_policy import DEFAULT_POLICY_PATH, ConservativeKPolicy, StateEncoder, baseline_action


class ConservativeBellmanTopKAgent(Agent):
    """Keep baseline ranking and change only the recommendation count."""

    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        *,
        policy_path: str | Path = DEFAULT_POLICY_PATH,
    ) -> None:
        super().__init__(catalog_path)
        self.k_policy = ConservativeKPolicy.load(policy_path)
        self.state_encoder = StateEncoder()
        self.decision_log: dict[str, list[dict[str, object]]] = {}

    def reset(self, session_id: str, user_profile: dict) -> None:
        super().reset(session_id, user_profile)
        self.decision_log[session_id] = []

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict:
        if session_id not in self.sessions:
            raise RuntimeError("reset must be called before respond")

        state = self.sessions[session_id]
        previous_signature = self.state_encoder.conversation_signature(state)
        previous_useful = {
            clue.key
            for clue, _matches, _kind in self.state_encoder.useful_evidence(self, state)
        }
        self._parse(state, user_message, turn)
        current_signature = self.state_encoder.conversation_signature(state)
        current_useful = {
            clue.key
            for clue, _matches, _kind in self.state_encoder.useful_evidence(self, state)
        }

        # Ranking is exactly the shared baseline. The frozen policy controls K only.
        ranked = super()._rank(state)
        policy_state = self.state_encoder.encode(
            self,
            state,
            turn=turn,
            last_evidence_gain=len(current_useful - previous_useful),
            last_reply_had_no_information=current_signature == previous_signature,
            ranked=ranked,
        )
        limit, reason = self.k_policy.choose(
            policy_state,
            requested_top_k=top_k,
        )
        unseen = [asin for asin in ranked if asin not in state.shown]
        chosen = unseen[:limit]
        if len(chosen) < limit:
            remaining = limit - len(chosen)
            chosen.extend([asin for asin in ranked if asin not in chosen][:remaining])
        state.shown.update(chosen)

        if state.other_calls < 3:
            ask_attribute: str | None = "other"
            state.other_calls += 1
        else:
            ask_attribute = None

        self.decision_log.setdefault(session_id, []).append(
            {
                "turn": int(turn),
                "state": policy_state.encode(),
                "k": int(limit),
                "baseline_k": baseline_action(turn, top_k),
                "reason": reason,
                "artifact_fingerprint": self.k_policy.fingerprint,
            }
        )
        return {
            "message": (
                "What other requirements matter most to you?"
                if ask_attribute
                else "Here are the closest remaining matches."
            ),
            "ask_attribute": ask_attribute,
            "recommendations": [{"parent_asin": asin} for asin in chosen],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }
