export type Character = Readonly<{
  id: string;
  name: string;
  role: string;
  portraitPath: string;
  aliases: readonly string[];
}>;

const character = (id: string, name: string, role: string, aliases: readonly string[] = []): Character => ({
  id,
  name,
  role,
  portraitPath: `/characters/${id}.png`,
  aliases,
});

export const CHARACTERS: readonly Character[] = [
  character("npc_zhao_jianguo", "赵建国", "常务副县长"),
  character("npc_zheng_xiangdong", "郑向东", "县长秘书"),
  character("npc_feng_jingzhi", "冯敬之", "县财政局长"),
  character("npc_he_xingbang", "贺兴邦", "县卫健局副局长"),
  character("npc_ke_qinian", "柯启年", "县环保站站长"),
  character("npc_qian_wei", "钱伟", "宏达化工法人代表"),
  character("npc_sun_qiang", "孙强", "渡口镇党委书记"),
  character("npc_zhang_li", "张立", "市委巡察组组长"),
  character("npc_gu_keming", "顾克明", "市生态环境局副局长"),
  character("npc_chen_mo", "陈默", "独立调查记者"),
  character("npc_wang_fang", "王芳", "县电视台记者"),
  character("npc_zhou_dashan", "周大山", "村支书兼主任"),
  character("npc_liu_san", "刘三", "村会计"),
  character("npc_wu_xiuying", "吴秀英", "退休教师"),
  character("npc_he_tiezhu", "何铁柱", "退伍军人"),
  character("npc_yuan_guilan", "袁桂兰", "困难户"),
  character("npc_ma_changshun", "马长顺", "小卖部老板"),
  character("npc_ning_dehai", "宁德海", "退休老党员", ["宁老"]),
  character("npc_tan_laoliu", "谭老六", "老上访户"),
  character("npc_yang_bo", "杨波", "返乡青年"),
  character("npc_zhou_kuiyuan", "周奎元", "周氏宗族执事"),
  character("npc_zhou_mancang", "周满仓", "周氏族人"),
  character("npc_shi_wenbin", "石文斌", "县环保站职工"),
  character("player_li_zhiyuan", "李致远", "云溪县县长、县委副书记", ["李县长"]),
  character("npc_jiang_chongyue", "蒋崇岳", "县委书记"),
  character("npc_deng_shouben", "邓守本", "柳林村独身老汉"),
  character("npc_miao_xiwang", "苗喜旺", "柳林村早签户"),
  character("npc_lao_juetou", "老倔头", "铁心不签的老人"),
  character("npc_luo_jian", "罗健", "县卫生院防疫科干部"),
  character("npc_cui_guanglin", "崔广林", "信访办卷宗室老同志"),
];

const CHARACTER_LOOKUP = new Map<string, Character>();

for (const entry of CHARACTERS) {
  for (const key of [entry.id, entry.name, ...entry.aliases]) {
    CHARACTER_LOOKUP.set(key.toLocaleLowerCase(), entry);
  }
}

export function resolveCharacter(...references: unknown[]): Character | null {
  for (const reference of references) {
    if (typeof reference !== "string") continue;
    const key = reference.trim().toLocaleLowerCase();
    if (!key) continue;
    const match = CHARACTER_LOOKUP.get(key);
    if (match) return match;
  }
  return null;
}
