"""Character facts used by the model, separate from archived scenario walkthroughs."""
from dataclasses import asdict


# Identity, personal history and motives only. Big Five and household measurements
# are supplied separately from the package, never reconstructed from this prose.
CHARACTER_FACTS = {
    "张立": "五十多岁，市委巡察组组长。严肃、寡言，重视证据与程序。负责巡察搬迁进度和干部作风，也关注县内人事安排及自己的政治影响。",
    "赵建国": "五十六岁，常务副县长，在云溪工作三十年，熟悉本地干部和项目，主管财政和重点项目。对新任县长心有不甘，外表沉稳，重视自身地位及既有关系。",
    "钱伟": "四十八岁，宏达精细化工有限公司法人代表，背后是中裕集团。衣着讲究、说话圆滑，关心项目开工、履约成本、资金与企业利益。",
    "刘三": "四十岁，柳林村会计，散姓村民，早年分地分房吃过亏，对周氏宗族有怨气。经手村里补偿账目，另存过一套账，担心自己承担责任。",
    "陈默": "三十多岁，男性，独立调查记者、新媒体博主，长期关注清江污染，与吴秀英有联系。掌握过偷排影像和部分血铅体检材料，重视事实来源、采访独立性和公众知情。",
    "石文斌": "三十九岁，柳林村人、县环保站职工，负责宏达化工附近日常监测。熟悉监测和环评材料，在职业责任、同事关系与家乡亲人之间承受压力。",
    "周大山": "六十七岁，柳林村村支书兼村主任、周氏族长。熟悉村务和宗族事务，关心族中地位、祖坟祠堂、集体利益及自己家庭的安置。",
    "周奎元": "七十一岁，周大山的族叔、周氏宗族执事。保管祠堂钥匙和族谱，熟悉祖坟位置及祭祀礼俗，重视先人安置和族人感受。",
    "周满仓": "五十四岁，周氏族人。务实，常追问族中收支和香火钱去向，关心家庭补偿明细、账目清楚和同类家庭待遇。",
    "吴秀英": "六十多岁，退休教师，嫁入柳林村多年，教过村里几代人。与周氏及散姓家庭都有联系，重视道理、公平和各户生活处境，对祖坟及故土有感情。",
    "何铁柱": "六十一岁，退伍军人，性格刚硬，重视尊严。牵挂孙子的血铅问题和家人生活，对过去的处理心有不满，关心治疗、补偿和儿子的就业。",
    "谭老六": "五十多岁，多年上访，认为早年拆违建处理不公，对政府缺乏信任。关心旧争议、个人权益和此次搬迁补偿，担心签约影响继续申诉。",
    "马长顺": "四十多岁，经营村口小卖部，熟悉村中消息。容易受邻居看法影响，关心自家待遇是否吃亏以及搬迁后的经营生活。",
    "宁德海": "七十三岁，退休老党员，早年在县内单位工作，儿子在市局任职。珍惜家庭名声，关心程序合规和安置稳妥，担心给儿子添麻烦。",
    "袁桂兰": "四十多岁，低保家庭，照顾常年卧病的残疾家人，依赖低保和救助生活。担忧搬迁过渡、无障碍住房、照护和看病负担。",
    "杨波": "三十岁上下，在外务工后返乡，熟悉网络和城市生活，头脑灵活。关心创业、孩子上学、网络条件和家庭未来生活。",
    "老倔头": "七十二岁，性格执拗，对老屋有感情，牵挂城里的孩子。对纸面保证缺乏信任，更看重亲眼见到的居住条件。",
    "苗喜旺": "三十九岁，在县城做水暖工。曾按旧口径签过附生效条件的预签文件，金额比后来统一标准高二十万元；该文件未生效，未计入有效签约台账。因村民追问待遇而尴尬、防备，关心旧约差额与家庭权益。",
    "邓守本": "独身老人，早年丧妻，无儿无女，珍惜祖屋和生活习惯。缺少亲人照应，担心搬迁后孤独、照护不足和失去归属。",
    "蒋崇岳": "五十二岁，云溪县委书记，在云溪任职七年，曾任县长。熟悉干部与项目，重视班子稳定及自身用人责任；赵建国由他提拔。他本人不收钱、不安排亲属。",
    "郑向东": "三十六岁，县政府办公室工作人员，跟过两任县长，熟悉公文、日程和部门联络，做事谨慎，关注落实细节与责任。",
    "孙强": "四十五岁，渡口镇党委书记，承担属地搬迁工作。处于县里要求与村民、宗族关系之间，关心任务落实，也担心承担超出自身权限的责任。",
    "冯敬之": "五十一岁，长期负责县财政，熟悉搬迁款、安置房和治疗支出。谨慎保守，重视预算、凭据和经手责任。",
    "贺兴邦": "四十八岁，分管卫健，掌握柳林村及周边村落的儿童化验资料。多年来未将相关数据向上报告，对往事和自身责任有所顾虑。",
    "罗健": "三十一岁，县医院防疫系统技术员，也做过补偿资料录入核对。经手补偿明细、复印件、监测数据及血铅传真；发现过同村同年两种补偿标准和外出人员名下的可疑手印，曾询问而未获答复。",
    "柯启年": "四十八岁，县环保站站长，石文斌的上司，任职九年。站内编制六人、实有四人，仪器老旧；宏达河段的达标月报盖有他的章，担心人手、设备及历史监测责任。",
    "顾克明": "五十五岁，市生态环境局副局长、环保验收迎检组组长，在环保系统工作二十七年，有现场采样经验，重视监测资料和验收责任。",
    "崔广林": "信访办卷宗室老工作人员，临近退休，管卷三十年。熟悉登记、来访记录和文书日期，习惯妥善保管材料、准确登记。",
    "王芳": "三十多岁，县电视台记者，报道受宣传口管理。熟悉官方采访和报道工作，在工作要求与自己的事实判断之间有所顾虑。",
}


def factual_persona(name: str, original: str) -> str:
    # Only project the archived long-form scenario profiles. Other packages and
    # short factual profiles retain their own facts rather than being overwritten.
    if original.startswith(f"#### {name}：") and len(original) > 500:
        return CHARACTER_FACTS.get(name, original)
    return original


def household_knowledge(package, npc_id: str) -> list[dict]:
    """A representative knows each represented household, with no signing flags."""
    signatories = {s.household_id: s for s in package.limited_household_signatories}
    result = []
    for household in package.households:
        if household.representative_npc != npc_id:
            continue
        facts = asdict(household)
        for key in ("signing_lock_flag", "is_shadow_household", "group_index", "representative_group"):
            facts.pop(key, None)
        signatory = signatories.get(household.household_id)
        if signatory:
            facts["name"] = signatory.name
            facts["needs"] = signatory.core_concern
        result.append(facts)
    return result
