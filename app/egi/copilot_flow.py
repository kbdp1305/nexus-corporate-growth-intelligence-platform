"""Context validation shared by Copilot views and action execution."""
from copy import deepcopy


def plan_matches(plan, rm, week_start=None):
    return bool(plan and plan.get('rm') == rm and plan.get('minggu_mulai') and
                (week_start is None or plan['minggu_mulai'] == week_start.isoformat()))


def plan_scope_error(plan, rm, allowed):
    if rm == 'Semua RM':
        return 'Pilih satu RM sebelum menyetujui rencana kunjungan.'
    if not plan_matches(plan, rm):
        return 'Rencana ini berasal dari konteks RM atau minggu yang berbeda. Susun ulang rencana.'
    if any(item.get('id') not in allowed for day in plan.get('hari', []) for item in day.get('item', [])):
        return 'Rencana memuat perusahaan di luar cakupan akun. Susun ulang rencana.'
    return None


def selected_plan(plan, selections):
    result = deepcopy(plan)
    for day_index, day in enumerate(result.get('hari', [])):
        day['item'] = [item for item in day['item'] if (day_index, item['id']) in selections]
        if day.get('intro') and day['intro'][1] not in {item['id'] for item in day['item']}:
            day.pop('intro', None)
    result['hari'] = [day for day in result['hari'] if day['item']]
    return result
