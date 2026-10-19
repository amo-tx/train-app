# -*- coding: utf-8 -*-
"""补齐 airports_full 中缺失的 cn_city(英文城市名 → 中文)。
119/235 机场缺中文名, 导致 _city_airports 查不到机场 → 空铁联运方向判断失效。"""
import sqlite3

CN = {
    "Taiyuan": "太原", "Hefei": "合肥", "Guiyang": "贵阳", "Xichang": "西昌",
    "Dongying": "东营", "Luoyang": "洛阳", "Dunhuang": "敦煌", "Chifeng": "赤峰",
    "Shijiazhuang": "石家庄", "Tongliao": "通辽", "Xilinhot": "锡林浩特",
    "Changde": "常德", "Nanyang": "南阳", "Xiangfan": "襄阳", "Xiangyang": "襄阳",
    "Ankang": "安康", "Golmud": "格尔木", "Hanzhong": "汉中", "Qingyang": "庆阳",
    "Yan'an": "延安", "Shangri-La": "香格里拉", "Luxi": "芒市", "Mangshi": "芒市",
    "Simao": "普洱", "Pu'er Simao": "普洱", "Ganzhou": "赣州", "Jingdezhen": "景德镇",
    "Quzhou": "衢州", "Linyi": "临沂", "Weifang": "潍坊", "Wuyishan": "武夷山",
    "Nanping Wuyishan": "武夷山", "Yancheng": "盐城", "Yiwu": "义乌", "Zhoushan": "舟山",
    "Mianyang": "绵阳", "Nyingchi": "林芝", "Karamay": "克拉玛依", "Heihe": "黑河",
    "Anqing": "安庆", "Qinhuangdao": "秦皇岛", "Jiayuguan": "嘉峪关",
    "Dongsheng": "鄂尔多斯", "Ordos": "鄂尔多斯", "Panzhihua": "攀枝花", "Hami": "哈密",
    "Tacheng": "塔城", "Mohe County": "漠河", "Mohe": "漠河", "Jining": "济宁",
    "Altay": "阿勒泰", "Wuhai": "乌海", "Xi'AN": "西安", "Xi'an": "西安",
    "Huizhou": "惠州", "Longyan": "龙岩", "Baoshan": "保山", "Xingyi": "兴义",
    "Zhijiang": "怀化", "Lincang": "临沧", "Tengchong": "腾冲", "Yushu": "玉树",
    "Shiquanhe": "阿里", "Zhongwei": "中卫", "Baise": "百色", "Burqin": "阿勒泰",
    "Kanas": "阿勒泰", "Handan": "邯郸", "Jixi": "鸡西", "Shigatse": "日喀则",
    "Bayannur": "巴彦淖尔", "Qianjiang": "潜江", "Baishan": "白山", "Tianshui": "天水",
    "Kangding": "康定", "Turpan": "吐鲁番", "Guyuan": "固原", "Lüliang": "吕梁",
    "Lvliang": "吕梁", "Daocheng": "稻城", "Xinyuan": "伊犁", "Zhangye": "张掖",
    "Anshan": "鞍山", "Tonghua": "通化", "Suzhou": "苏州", "Erenhot": "二连浩特",
    "Hechi": "河池", "Fuyuan": "抚远", "Liupanshui": "六盘水", "Shennongjia": "神农架",
    "Zhangjiakou": "张家口", "Arxan": "阿尔山", "Ngawa": "阿坝", "Jinchuan": "金昌",
    "Fuyun": "富蕴", "Sanming": "三明", "Guanghua": "广州", "Shiyan": "十堰",
    "Mengnai": "茫崖", "Huatugou": "茫崖", "Bengbu": "蚌埠", "Rugao": "如皋",
    "Wuhu": "芜湖", "Shanshan": "鄯善", "Yingkou": "营口",
    "Alxa Left Banner": "阿拉善左旗", "Haixi": "海西", "Qionghai": "琼海",
    "Wulanchabu": "乌兰察布", "Ulanqab": "乌兰察布", "Shaoyang": "邵阳",
    "Baicheng": "白城", "Longnan": "陇南", "Songyuan": "松原", "Jiansanjiang": "建三江",
    "Zunyi": "遵义", "Libo": "荔波", "Chengde": "承德", "Wudalianchi": "五大连池",
    "Ejin Banner": "额济纳旗", "Alxa Right Banner": "阿拉善右旗",
    "Holingol": "霍林郭勒", "Golog": "果洛", "Yarkant": "莎车", "Cangyuan": "沧源",
    "Lancang Lahu": "普洱", "Xinzhou": "忻州", "Zhalantun": "扎兰屯",
    "Yuanmou": "元谋", "Xingcheng": "兴城",
}

con = sqlite3.connect("data/train.db")
cur = con.cursor()
rows = cur.execute(
    "SELECT iata, city FROM airports_full WHERE cn_city='' OR cn_city IS NULL").fetchall()
fixed, missed = 0, []
for iata, city in rows:
    cn = CN.get((city or "").strip())
    if cn:
        cur.execute("UPDATE airports_full SET cn_city=? WHERE iata=?", (cn, iata))
        fixed += 1
    else:
        missed.append((iata, city))
con.commit()
total = cur.execute("SELECT COUNT(*) FROM airports_full WHERE cn_city='' OR cn_city IS NULL").fetchone()[0]
print("修复 %d 个机场中文名, 剩余缺失 %d" % (fixed, total))
if missed:
    print("未覆盖:", missed)
