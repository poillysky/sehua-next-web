# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, ".")
from app.prefix.maker_names import (
    resolve_maker_intro_for_prefix,
    resolve_maker_names,
    load_prefix_maker_base,
    PREFIX_I18N,
    MAKER_I18N,
    MAKER_INTRO,
    _intro_for_maker_key,
)

for pref in ("LUXU", "DDT", "DOCP", "SONE"):
    print("=" , pref)
    print(" base", load_prefix_maker_base().get(pref))
    print(" i18n", PREFIX_I18N.get(pref))
    print(" names", resolve_maker_names(pref))
    print(" intro", resolve_maker_intro_for_prefix(pref))
    # which key hits aurora
    aurora_keys = [k for k,v in MAKER_INTRO.items() if "オーロラ" in v]
    print(" aurora intro keys", aurora_keys[:5])
