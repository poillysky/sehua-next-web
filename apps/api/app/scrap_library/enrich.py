# -*- coding: utf-8 -*-
"""刮削库元数据补全：按配置片商源拉详情 → 写回 NFO/封面 → 重嵌入。"""
from __future__ import annotations
import json
import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from pathlib import Path
from typing import Any
import app.scrap_library.embed as embed_svc
from app.ai.config import resolve_embed_config
from app.ai.embed import encode_texts_sync
from app.core.db import get_meta_pool, media_dir
from app.scrap_library.nfo import (
    build_mdcx_nfo_root,
    fields_from_movie_root,
    parse_nfo,
    write_nfo,
)
from app.scrap_library import enrich_monitor as enrich_mon


log = logging.getLogger(__name__)


from app.scrap_library.enrich_runtime import (  # noqa: E402
    _QUEUE_SCAN_LOCK,
    _QUEUE_SCAN_STATE,
    _checkpoint_summaries,
    _enrich_hydrate_lock,
    _enrich_hydrated,
    _enrich_job,
    _enrich_lock,
    _enrich_percent,
    _enrich_retry_front,
    _hydrate_enrich_runtime,
    _persist_enrich_runtime,
    _set_progress,
    _set_queue_scan_progress,
    _strategy_epoch,
    _strategy_epoch_mu,
    bump_strategy_epoch,
    notify_enrich_watchers,
    subscribe_enrich_updates,
    unsubscribe_enrich_updates,
)


_ENRICH_KINDS = (
    "no_local",
    "no_media",
    "no_actress",
    "no_studio",
    "no_plot",
    "thin_title",
)


_DEFAULT_ENRICH_KINDS = tuple(_ENRICH_KINDS)


_ITEM_WORKERS_DEFAULT = 6


_ITEM_WORKERS_MAX = 16


_COVER_JOB_WORKERS_MIN = 8


_COVER_JOB_WORKERS_MAX = 16


_COVER_JOB_WORKERS = _COVER_JOB_WORKERS_MAX  # ThreadPool 硬上限


_SOURCE_WORKERS_MAX = 64


_RESULTS_MEM_CAP = 80


_SCAN_QUEUE_SOURCES = frozenset({"local_scan", "scan"})


_cover_job_pool: Any = None


_cover_job_pool_lock = threading.Lock()


_cover_gate_lock = threading.Condition(_cover_job_pool_lock)


_cover_gate_inflight = 0


_cover_gate_target = _COVER_JOB_WORKERS_MIN


_poster_ok_cache: dict[tuple[str, int, int], bool] = {}


_finish_prune_counter = 0


_finish_prune_lock = threading.Lock()


from app.scrap_library.enrich_junk import (  # noqa: E402
    _ACT_TAG_FRAG_RE,
    _JUNK_ACTORS,
    _JUNK_ACTOR_SUBSTR,
    _JUNK_ACTOR_TAGS,
    _JUNK_TAGS,
    _JUNK_TITLE_MARKERS,
)


# ==========================================================================
# 以下名字已搬到兄弟模块；此处再导出，保证 `enrich.NAME` 调用/打补丁零改动。
# 注意：必须放在文件末尾 —— 兄弟模块会回引本模块的名字，
#       等本模块顶层全部定义完再导入，才能避免循环导入。
# ==========================================================================
from app.scrap_library.enrich_retry_api import (  # noqa: E402
    _CLASSIFIED_SKIP_TTL_SEC,
    _COVER_FAIL_LABEL,
    _COVER_ONLY_GAPS,
    _DONE_LOG_RE,
    _FOLDER_GAPS_CACHE_CAP,
    _GAP_FAIL_LABEL,
    _LIB_PROGRESS_COUNTS_TTL_SEC,
    _LOCAL_NFO_MAPS_CACHE_MAX,
    _LOCAL_NFO_MAPS_TTL_SEC,
    _SOFT_GAP_LABELS,
    _SOFT_SUCCESS_GAPS,
    _SOURCE_COOLDOWN_LOCK,
    _SOURCE_COOLDOWN_UNTIL,
    _SOURCE_DOWN_STREAK,
    _STALE_RUNNING_MIN_INTERVAL_SEC,
    _SUCCESS_BLOCK_GAPS,
    _classified_skip_cache,
    _demoted_false_dones,
    _folder_gaps_cache,
    _folder_gaps_cache_lock,
    _fresh_vector_library_total,
    _incomplete_cache,
    _invalidate_classified_skip_cache,
    _lib_progress_counts_cache,
    _local_nfo_maps_cache,
    _maybe_prune_done_logs,
    _pending_backfill_done,
    _promoted_actress_soft,
    _retry_hint_cache,
    _retry_hint_known,
    _retry_hint_primed,
    _soft_correction_last,
    _stale_running_last,
    retry_enrich_fails,
    retry_enrich_softs,
)
from app.scrap_library.enrich_hints import (  # noqa: E402
    _TITLE_TAIL_NOISE,
    _TRAD_HINT_RE,
    _give_up_kind,
    _refine_kind_with_meter,
    _retry_hint_note,
)
from app.scrap_library.enrich_folder_io import (  # noqa: E402
    _persist_enrich_result_to_queue_log,
    patch_folder_meta_no_embed,
    reingest_folder,
)
from app.scrap_library.enrich_one import enrich_one_row  # noqa: E402
from app.scrap_library.enrich_runner import run_enrich  # noqa: E402
from app.scrap_library.enrich_job_api import (  # noqa: E402
    enrich_one_by_item_id,
    save_item_plot,
    start_enrich_job,
)
from app.scrap_library.enrich_maps import (  # noqa: E402
    _CN_TEXT_SOURCE_IDS,
    _CN_WAIT_BUDGET_SEC,
    _GAP_FIELD_PRIORITY_KEYS,
    _META_FILL_SOURCE_IDS,
    _META_WAIT_BUDGET_SEC,
    _TRAILING_ALT_CODE_RE,
    _apply_mdcx_maps,
    _cn_text_ids_in_batch,
    _cover_job_slot,
    _get_cover_job_pool,
    _maybe_llm_fill_zh,
    _polish_studio_name,
    _soft_retry_fill_actors,
    _title_is_thin,
)
from app.scrap_library.enrich_job_control import (  # noqa: E402
    _clear_runtime_queue,
    _fill_mode_to_job_mode,
    _next_budget,
    request_enrich_cancel,
    request_enrich_pause,
    request_enrich_stop,
)
from app.scrap_library.enrich_queue_io import (  # noqa: E402
    _COUNTS_CACHE_TTL_SEC, _LOCAL_STATUS_TOTALS, _LOCAL_STATUS_TOTALS_LOADED, _LOCAL_STATUS_TOTALS_LOCK,
    _QUEUE_SAMPLE_LIMIT, _STATUS_QUEUE_HEAVY_KEYS, _counts_cache, _counts_ok_cache, _enrich_log_sink,
    _ensure_local_status_totals_loaded, _hist_log_cache, _hydrate_queue_item_from_library,
    _lift_local_status_totals_from_counts, _local_status_totals_path, _patch_queue_item, _push_log,
    _queue_log_insert_many, _queue_log_region, _queue_log_update_row, _queue_sample_cache,
    _sample_queue_for_status, _scrape_counts_cache, _set_current, _set_current_region, _set_queue,
    _write_enrich_log_batch, iter_enrich_pending_batches, iter_enrich_pending_items, load_queue_log,
)
from app.scrap_library.enrich_checkpoint import (  # noqa: E402
    _save_checkpoint, _clear_checkpoint, _take_checkpoint, _peek_checkpoint, _slim_checkpoint_queue, _CHECKPOINT_PERSIST_QUEUE_MAX,
    _checkpoint_for_persist, _rebuild_checkpoint_queue_from_log,
)
from app.scrap_library.enrich_cover import (  # noqa: E402
    _cover_fail_message, _poster_rank, _dmm_poster_fallbacks, _rewrite_cover_host_mirrors, _normalize_cover_entries, _cover_job_workers_target,
    _download_covers, _purge_extra_cover_files, _local_poster_ok, _stat_is_file, _local_poster_ok_uncached, _local_success_disk_ok,
    _LOCAL_COVER_FILES, list_local_covers, _purge_blank_covers,
)
from app.scrap_library.enrich_detail import (  # noqa: E402
    _detail_usable, _detail_from_local_folder, _backfill_queue_item_detail, _collect_nfo_folders_parallel, _classify_disk_gaps, _detail_field_rows,
    _fields_after_local_write, _source_in_cooldown, _note_source_fetch_outcome, _src_give_up_reason, _classify_source_failure, _safe_local_gaps,
    _detail_sources, _identity_gate_details, _detail_has_poster, _detail_has_actors, _detail_satisfies_gaps, _prioritize_batch_for_gaps,
    _detail_meta_incomplete, _may_early_stop, _gaps_likely_ready, _fetch_detail, _find_nfo, _ensure_child,
    _resolve_enrich_folder,
)
from app.scrap_library.enrich_history import (  # noqa: E402
    _ENRICH_LOG_KEEP, _ENRICH_LOG_RETURN, _ENRICH_LOG_MEMORY, _enrich_log_region_keys, _canonical_enrich_log_region, _persist_enrich_log,
    flush_enrich_logs, enrich_log_sink_stats, load_enrich_logs, _HIST_LOG_TTL_SEC, _load_enrich_logs_cached, _clear_enrich_logs,
    clear_enrich_logs, _recover_done_from_enrich_logs,
)
from app.scrap_library.enrich_merge import (  # noqa: E402
    _halt_kind, current_strategy_epoch, _note_strategy_hot_if_needed, apply_live_strategy, _field_priority_applies, _strategy_field_priority,
    _strategy_region_sources, _merge_source_allowed, _pick_by_field_priority, _merge_got, _FIELD_LAUNCH_ORDER, _merge_enrich_sidecar_into_item,
    _set_text_if_empty, _merge_list_tags, _merge_actors, merge_nfo_with_detail,
)
from app.scrap_library.enrich_queue import (  # noqa: E402
    _QUEUE_LOG_DONE_KEEP, _QUEUE_LOG_PRUNE_EVERY, _QUEUE_LOG_STATUSES, _QUEUE_LOG_FILTER_STATUSES, _QUEUE_LOG_PAYLOAD_KEYS, _QUEUE_SCAN_SAMPLE_CAP,
    _QUEUE_SCAN_NOTIFY_GAP, _queue_scan_preview_item, _queue_scan_snapshot, _queue_scan_add_sample, _clear_queue_scan_progress, _queue_log_status_counts_db_ex,
    _queue_log_status_counts_db, _queue_log_scrape_counts_db, _queue_log_status_counts, _queue_log_int_id, _queue_log_payload, _queue_log_read_payload,
    _queue_log_insert_params, _queue_log_row_to_item, _clear_queue_log, _queue_log_mark_pending, _queue_log_reopen_running, _queue_log_reopen_stale_running,
    _queue_log_reopen_fails, _queue_log_reopen_softs, _queue_log_find_open, _queue_log_done_keys, _ensure_queue_log_ids, _queue_log_prune_pending_not_in,
    _queue_log_prune_open_if_done, _queue_log_prune_done_keep, _queue_log_prune_pending_if_running, _queue_log_clear_pending, _queue_log_classified_skip_keys, _queue_log_trim_inflated_pending,
    _queue_log_clear_local_scan_status, _QUEUE_LOG_INSERT_CHUNK, _queue_log_insert_local_status_samples, _queue_row_status, _queue_counts_of, _sample_queue_uncached,
    _queue_row_match_index, _payload_field_code, _queue_log_demote_false_dones, _queue_log_demote_false_dones_budgeted, _queue_log_promote_actress_soft_fails, _queue_log_normalize_soft_to_full_success,
)
from app.scrap_library.enrich_retry import (  # noqa: E402
    _SOFT_OK_PREFIX, _SOFT_OK_PREFIXES, _SOFT_PROMOTE_RULE_VER, _SOFT_CORRECTION_MIN_INTERVAL_SEC, _gap_labels, _strip_soft_ok_prefix,
    _is_soft_ok_error, _format_soft_ok_error, _soft_done_sql_pred, _is_soft_remain_error, _soft_gaps_from_remain_error, _RETRY_KIND_COVER,
    _RETRY_KIND_SRC_DOWN, _COVER_RETRY_MAX, _SRC_DOWN_RETRY_MAX, _RETRY_HINT_CACHE_TTL, _retry_next_state, _is_cover_only_gaps,
    _SRC_GIVEUP_POLL_SEC, _SOURCE_COOLDOWN_STREAK, _SOURCE_COOLDOWN_SEC, _MISS_HINTS, _CancelPair, _src_retry_item,
    _retry_hint_load, _retry_hint_invalidate, _retry_hint_clear_region, _retry_hint_clear_codes, _cover_giveup_codes, _should_skip_for_giveup,
    _note_retry_hints, _apply_local_gap_success, _ensure_actress_soft_promoted, _is_cancelled,
)
from app.scrap_library.enrich_scan import (  # noqa: E402
    _SQL_NOT_SCAN_SOURCE, _SQL_IS_SCAN_SOURCE, _CachedLocalMapsMarker, _local_nfo_maps_cache_get, _local_nfo_maps_cache_put, _region_local_dirs,
    _local_scan_workers, _folder_gaps_cache_cap, _SCAN_STREAM_FLUSH, _folder_gaps_stamp, _local_folder_gaps, iter_local_incomplete_items,
    _local_status_item, _LocalNfoMaps, _local_nfo_gap_maps, _rebuild_region_queue_from_scan, _replace_pending_from_vector, _hot_prefixes_for_region,
    scan_enrich_queue, _code_search_match, _lookup_code_from_scan_samples, _lookup_code_outside_queue_log,
)
from app.scrap_library.enrich_sidecar import (  # noqa: E402
    _file_stamp, _ENRICH_SIDECAR_LEGACY, _ENRICH_SIDECAR_VER, _enrich_sidecar_code, _enrich_sidecar_path, write_enrich_sidecar,
    read_enrich_sidecar,
)
from app.scrap_library.enrich_status import (  # noqa: E402
    _persist_local_status_totals, _set_local_status_totals, _clear_local_status_totals, _apply_local_status_totals, _region_counts_ok, _slim_one_result_mem,
    _pending_total_estimate, _clamp_pending_badge, _pending_page_from_vector, _slim_queue_row_for_status, _slim_queue_for_status, _slim_current_for_status,
    _slim_result_for_status, _progress_from_queue_counts, _region_library_progress, get_enrich_status, _cap_status_queue, _empty_queue_counts,
)
from app.scrap_library.enrich_text import (  # noqa: E402
    _NAME_PAIR_CENSOR_RESTORE, _looks_like_actor_sentence_frag, _is_platform_exclusivity_label, _looks_like_act_tag_token, _looks_like_person_name_tag, _names_from_title_pairs,
    _actress_disp_id, _unique_identity_names, _estimate_cast_size, _collapse_few_actress_variants, _titles_compatible, _actors_lifted_from_tags,
    _fold_tag_variant, _fold, _clean_tags, _has_cjk, _has_kana, _has_traditional,
    _has_han, _zh_prefer_bonus, _title_lacks_zh, _normalize_merged_title, _normalize_merged_overview, _mt_junk_penalty,
    _title_trailing_person_name, _title_actress_mismatch_penalty, _score_title, _title_should_prefer_map, _norm_code_token, _trailing_alt_code,
    _strip_trailing_alt_code, _overview_foreign_actress_penalty, _score_overview, _score_studio, _score_date, _score_year,
    _score_actors, _score_poster, _score_tags, _normalize_tag_alias, _pick_best_str, _actor_hints_from_titles,
    _text_needs_zh_llm, _zh_fill_acceptable, _align_llm_text_actors, _got_has_zh_title, _got_has_zh_plot, _prune_junk_actors,
    _replace_actors, _replace_list_tags,
    _is_plausible_actress_name, _clean_actors,
)
