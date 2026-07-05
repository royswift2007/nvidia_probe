from __future__ import annotations

from datetime import datetime, timedelta, timezone

from nvidia_probe.models import NormalizedModel, select_models_hybrid_topn


def make_model(index: int, calls: int, age_days: int) -> NormalizedModel:
    created_at = (datetime.now(timezone.utc) - timedelta(days=age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return NormalizedModel(
        model_id=f"vendor/model-{index:02d}",
        display_name=f"Model {index:02d}",
        model_type="chat",
        is_free=True,
        api_calls_30d=calls,
        api_calls_30d_display=str(calls),
        created_at_utc=created_at,
    )


models: list[NormalizedModel] = []

# 前 6 个模型既是 30 天调用量最高的稳定热门候选，也是新上架的高热度候选。
# 修复前稳定池会先吃掉它们，导致新晋热门池计数不足。
for index in range(1, 7):
    models.append(make_model(index, 2_000_000 - index, 2))

# 其余模型是老模型，用于填满稳定热门池。
for index in range(7, 31):
    models.append(make_model(index, 1_000_000 - index, 120))

selection = select_models_hybrid_topn(
    models,
    top_n=20,
    stable_ratio=0.7,
    trending_count=6,
    newest_count=0,
    new_model_days=14.0,
)

assert selection.summary["selected_count"] == 20, selection.summary
assert selection.summary["stable_count"] == 14, selection.summary
assert selection.summary["trending_count"] == 6, selection.summary
assert selection.summary["newest_count"] == 0, selection.summary
assert sum(1 for model in selection.selected if model.selection_bucket == "stable_popular") == 14
assert sum(1 for model in selection.selected if model.selection_bucket == "trending_new") == 6
assert {model.model_id for model in selection.selected if model.selection_bucket == "trending_new"} == {
    f"vendor/model-{index:02d}" for index in range(1, 7)
}
assert len({model.model_id for model in selection.selected}) == 20

print("hybrid-topn-ok")
