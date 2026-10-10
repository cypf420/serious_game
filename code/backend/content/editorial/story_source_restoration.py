"""Audited player-paragraph recovery, not a general importer or a script rewrite.

Line references address the user's backend-0c15d36/最终剧本.md. Hash pinning
prevents a later source edit from silently importing different passages.
"""
import hashlib
import re


SOURCE_SHA256 = '648041c97cab18edaf945cfa775351212b7b05dea4d789bbe5c3527d71481614'
SOURCE_RESTORATIONS = [
    {'issue': 'R04', 'day': 2, 'lines': [2554, 2558, 2560], 'mode': 'fixed_quotes_before_live_talk; departure_only_in_existing_conversation_completion'},
    {'issue': 'R06', 'day': 17, 'lines': [3541], 'mode': 'verbatim_player_paragraph'},
    {'issue': 'R07', 'day': 34, 'lines': list(range(5004, 5025, 2)), 'mode': 'verbatim_player_paragraphs'},
    {'issue': 'R03', 'day': 46, 'lines': [6462, 6464, 6466, 6468, 6508, 6518],
     'mode': 'legacy_return_shortcut_skips_redundant_custody_question; unknown witness template uses existing DP6-06.b instead of handing over an unowned original'},
    {'issue': 'R08', 'day': 59, 'lines': [7651, 7653, 7655, 7691],
     'mode': 'restore_advance_visit_before_existing_city_inspector_arrival'},
    {'issue': 'R10', 'day': 61, 'lines': [7940, 8023],
     'mode': 'retain_named_worklist_without_asserting_fixed_unsigned_counts'},
]
UNRESOLVED_SOURCE_ISSUES = {
    'R01': [7073, 7074],
    'R02': [3960, 7027],
    'R05': [2665, 2935, 7132],
    'R09': [3519, 7704],
    'R11': [12491, 12533],
    'R12': [3734, 3750, 12642, 12668],
    'R13': [11443],
}


def source_lines(raw):
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        from content.editorial.story_author_revision import read_source_edition
        return read_source_edition(raw)[0]
    return raw.decode('utf-8-sig').splitlines()


def apply_source_restoration(docs, source):
    ds = {d['decision_id']: d for d in docs['decisions.json']['decisions']}
    bs = {b['story_day']: b for b in docs['story_beats.json']['beats']}

    def block(number, scene, phase='scene'):
        text = source[number - 1].strip()
        if not text or text.startswith((':::', '#', '**', '- ')):
            raise ValueError(f'Not an audited player paragraph: {number}')
        result = dict(block_id=f'source_restore_l{number}', kind='narration',
                      text=text, scene_id=scene, presentation_phase=phase)
        dialogue = re.fullmatch(r'([^：「」]+)：「(.+)」', text)
        if dialogue:
            result.update(kind='dialogue', speaker=dialogue[1], text=dialogue[2])
        return result

    wu = ds['dp1_01_taskforce_faction_map']
    first, reference = wu['followup_blocks']
    scene = reference['scene_id']
    wu['followup_blocks'] = [first, block(2554, scene, 'followup'), reference,
                             block(2558, scene, 'followup')]

    bs[17]['opening_blocks'].insert(-1, block(3541, ds['dp2_01']['scene_id']))

    luo = ds['dp3_04']
    luo['presentation_blocks'] = [
        *(block(n, luo['scene_id']) for n in range(5004, 5025, 2)),
        *luo['presentation_blocks'],
    ]

    # The event queue resolves EV4-04 before DP4-10. Main arrival belongs to
    # the latter, not the day's opening. Preserve the reviewed city-level role.
    arrival = bs[59]['opening_blocks'][0]
    bs[59]['opening_blocks'] = [block(n, arrival['scene_id']) for n in (7651, 7653, 7655)]
    ds['dp4_10']['presentation_blocks'].insert(0, arrival)

    # Source 8023 supplies identities, but its fixed 13 unsigned households
    # contradict the interactive contract ledger. This is a verification list,
    # not a new claim that these families are unsigned or a new signing effect.
    names = re.findall(r'(周奎元|周满仓|马长顺|宁德海|老倔头|苗喜旺|邓守本)[一二两三]户', source[8022])
    if len(names) != 7:
        raise ValueError('Final-script chapter-five worklist differs from the reviewed source')
    scene = ds['dp5_01']['scene_id']
    bs[61]['opening_blocks'].extend([
        dict(block_id='d61_roster_recheck', kind='narration', scene_id=scene,
             presentation_phase='scene', text='台账摊在桌面上。郑向东把逐户记录翻开，已签署的协议与尚待办理的事项分开核对。'),
        dict(block_id='d61_named_worklist', kind='dialogue', speaker='郑向东', scene_id=scene,
             presentation_phase='npc', text='这轮要核对的有'+ '、'.join(names)+'。已经办结的核实履约，仍有争议的继续逐户处理；还差多少户，以实际签约台账为准。'),
    ])
    d = ds['dp5_01']
    replacements = {
        '十三户挪进待议栏': '未决家庭挪进待议栏',
        '十三户就是本章的正事': '未决家庭就是本章的正事',
        '全花在这七个人身上': '全花在名册上尚未解决的事项上',
        '说明十三户的状况': '说明未决家庭的实际状况',
        '你把十三户的名单钉在了会议室的墙上': '你把尚未解决的逐户事项钉在了会议室的墙上',
    }
    for option in d['options']:
        for key in ('text', 'consequence'):
            for before, after in replacements.items():
                option[key] = option[key].replace(before, after)

    # Test-driver repair only: the return template cannot hand the same original
    # to the reporter on D83. B has the same cooperation flags, without custody
    # transfer. Targets, contracts, thresholds and all player effects stay fixed.
    template = docs['acceptance_route_profiles.json']['decision_policy_templates']['unknown']
    if template['dp4_01'] != 'e' or template['dp6_06'] != 'a':
        raise ValueError('Unexpected original-custody witness baseline')
    template['dp6_06'] = 'b'
