/**
 * 色花堂论坛板块树（对齐 sehuatang/backend/parsers/boards.py）
 * 用于「分类资源 → 色花堂板块」直达真实 fid / 子分类。
 */

export type ForumRegionId = "japan" | "china" | "western" | "mixed" | "other";

export type ShtForumType = {
  key: string;
  fid: string;
  typeid: string;
  name: string;
  type_name: string;
  board_name: string;
  /** 日本 / 国产 / 欧美；通常由覆盖或默认推断填充 */
  region?: ForumRegionId;
};

export type ShtForumBoard = {
  name: string;
  fid: string;
  /** 无子分类时整板浏览 */
  types: ShtForumType[];
};

export type ShtForumCategory = {
  category: string;
  boards: ShtForumBoard[];
};

function types(
  fid: number,
  boardName: string,
  pairs: [string, string][],
): ShtForumType[] {
  return pairs
    .filter(([, typeName]) => !typeName.includes("版务"))
    .map(([typeid, typeName]) => ({
      key: `${fid}:${typeid}`,
      fid: String(fid),
      typeid,
      name: `${boardName} · ${typeName}`,
      type_name: typeName,
      board_name: boardName,
    }));
}

function board(
  fid: number,
  name: string,
  pairs: [string, string][] = [],
): ShtForumBoard {
  return {
    name,
    fid: String(fid),
    types: pairs.length ? types(fid, name, pairs) : [],
  };
}

/** 色花堂板块目录 */
export const SEHUATANG_FORUM: ShtForumCategory[] = [
  {
    category: "综合讨论区",
    boards: [
      board(95, "综合讨论区", [["716", "情色分享"]]),
      board(141, "网友原创区", [
        ["689", "国产合集"],
        ["690", "欧美合集"],
        ["691", "日本合集"],
        ["844", "合集推荐"],
        ["692", "破解"],
        ["705", "增强"],
        ["867", "换脸"],
        ["866", "自压"],
        ["879", "主播录播"],
        ["695", "套图"],
        ["694", "蓝光原盘"],
        ["693", "二次元"],
        ["696", "其它"],
      ]),
      board(142, "转帖交流区", [
        ["697", "国产自拍"],
        ["698", "直播视频"],
        ["699", "亚洲无码"],
        ["700", "亚洲有码"],
        ["701", "偷拍視頻"],
        ["702", "动漫/二次元"],
        ["703", "欧美风情"],
        ["704", "其他資源"],
        ["706", "合集资源"],
      ]),
    ],
  },
  {
    category: "原创BT电影",
    boards: [
      board(2, "国产原创", [
        ["684", "国产无码"],
        ["685", "主播录制"],
        ["686", "360水滴"],
        ["687", "厕所偷拍"],
      ]),
      board(36, "亚洲无码原创", [
        ["368", "FC2PPV"],
        ["369", "HEYZO"],
        ["370", "加勒比系列"],
        ["371", "一本道系列"],
        ["372", "10musume"],
        ["373", "女体のしんぴ"],
        ["374", "pacoma"],
        ["375", "heyppv"],
        ["379", "店長推薦"],
        ["449", "东京热"],
        ["523", "熟女俱樂部"],
        ["537", "xxx-av"],
        ["551", "人妻斬り"],
        ["552", "エッチな0930"],
        ["553", "エッチな4610"],
        ["583", "本生素人TV"],
        ["586", "sm-miracle"],
        ["587", "roselip-fetish"],
        ["589", "legsjapan"],
        ["590", "uralesbian"],
        ["591", "fellatiojapan"],
        ["618", "spermmania"],
        ["619", "handjobjapan"],
        ["631", "urabukkake"],
        ["654", "无码流出"],
        ["660", "金髪天國"],
        ["671", "加勒比PPV"],
        ["672", "无码破解"],
        ["683", "レズのしんぴ"],
        ["723", "japornxxx"],
        ["724", "盗窃系列"],
        ["822", "cospuri"],
      ]),
      board(37, "亚洲有码原创"),
      board(103, "高清中文字幕", [
        ["480", "有码高清"],
        ["481", "无码高清"],
      ]),
      board(107, "三级写真", [
        ["592", "日本写真"],
        ["593", "韩国三级"],
        ["594", "日本三级"],
        ["595", "美国三级"],
        ["596", "香港三级"],
        ["597", "国产三级"],
        ["598", "法国三级"],
        ["599", "美国四级"],
        ["600", "国产四级"],
        ["601", "英国四级"],
        ["602", "英国三级"],
        ["603", "台湾四级"],
        ["604", "泰国三级"],
        ["605", "法国四级"],
        ["606", "加拿大三级"],
        ["607", "意大利三级"],
        ["608", "荷兰三级"],
        ["609", "台湾三级"],
        ["610", "挪威三级"],
        ["611", "瑞士三级"],
        ["612", "瑞士四级"],
        ["613", "香港四级"],
        ["614", "阿根廷三级"],
        ["615", "泰国四级"],
        ["616", "波兰三级"],
        ["617", "国产写真"],
        ["620", "西班牙三级"],
        ["621", "墨西哥三级"],
        ["622", "俄罗斯三级"],
        ["623", "美国写真"],
        ["624", "德国三级"],
        ["625", "丹麦三级"],
        ["628", "克罗地亚三级"],
        ["629", "巴西三级"],
        ["630", "意大利四级"],
        ["633", "德国四级"],
        ["634", "瑞典四级"],
        ["645", "丹麦四级"],
        ["646", "荷兰写真"],
        ["650", "比利时四级"],
        ["655", "澳大利亚三级"],
        ["656", "印度三级"],
        ["657", "菲律宾三级"],
        ["658", "新加坡写真"],
        ["659", "韩国写真"],
        ["667", "法国写真"],
        ["668", "英国写真"],
        ["669", "俄罗斯写真"],
        ["670", "智利三级"],
      ]),
      board(160, "VR视频区"),
      board(104, "素人有码系列", [
        ["726", "SIRO"],
        ["727", "259LUXU"],
        ["728", "300MIUM"],
        ["729", "332NAMA"],
        ["730", "326EVA"],
        ["731", "328HMDN"],
        ["533", "G-area"],
        ["534", "Mywife"],
        ["535", "S-cute"],
        ["536", "FC2"],
        ["557", "himemix"],
        ["563", "getchu"],
        ["588", "siro-hame"],
        ["626", "r-file"],
        ["627", "giga-web"],
        ["632", "knights-visual"],
        ["725", "230OREX"],
        ["807", "336KNB"],
        ["808", "200GANA"],
        ["809", "300MAAN"],
        ["810", "300NTK"],
        ["811", "390JAC"],
        ["812", "326SCP"],
        ["813", "其他系列"],
      ]),
      board(38, "欧美无码"),
      board(151, "4K原版", [
        ["823", "无码"],
        ["824", "有码"],
      ]),
      board(152, "韩国主播"),
      board(39, "动漫原创", [
        ["404", "无码"],
        ["405", "有码"],
      ]),
    ],
  },
];

export function shtForumBoardCount(): number {
  return SEHUATANG_FORUM.reduce((n, c) => n + c.boards.length, 0);
}

export function shtForumPreview(): string {
  return SEHUATANG_FORUM.map((c) => c.category).join(" · ");
}
