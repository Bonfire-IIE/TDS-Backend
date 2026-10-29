"""National-standard code tables used by data-resource registration.

Sources (kept in ``files/resources``):

* GB/T 4754-2017 国民经济行业分类 -- industry sections A-T.
* GB/T 21063.4 政务信息资源目录体系 第4部分 附录A -- theme classification.
  First-level codes use A-W without I and O; second-level codes are
  ``Z<first><second>00``.
* 《数据基础设施 数据目录描述要求》(征求意见稿) 附录A 表A.1 -- data source,
  personal information, quality, high-quality dataset, AI readiness, AI task
  type, data modality, synthetic data and AI training authorization codes.

Security levels follow the existing center contract (general_1 / general_2 /
important).  Core data is deliberately absent: the platform does not host it.

The tables are the single source of truth for both validation and the demo UI
(``GET /api/v1/metadata-options``).  Mapping fields to these codes is not a
claim of full standard conformance certification.
"""

INDUSTRIES = {
    "A": "农、林、牧、渔业",
    "B": "采矿业",
    "C": "制造业",
    "D": "电力、热力、燃气及水生产和供应业",
    "E": "建筑业",
    "F": "批发和零售业",
    "G": "交通运输、仓储和邮政业",
    "H": "住宿和餐饮业",
    "I": "信息传输、软件和信息技术服务业",
    "J": "金融业",
    "K": "房地产业",
    "L": "租赁和商务服务业",
    "M": "科学研究和技术服务业",
    "N": "水利、环境和公共设施管理业",
    "O": "居民服务、修理和其他服务业",
    "P": "教育",
    "Q": "卫生和社会工作",
    "R": "文化、体育和娱乐业",
    "S": "公共管理、社会保障和社会组织",
    "T": "国际组织",
}

DATA_SOURCE_TYPES = {
    "01": "原始取得",
    "02": "收集取得",
    "03": "交易取得",
    "04": "共享取得",
    "05": "其他",
}

SECURITY_LEVELS = {
    "general_1": "一般数据一级",
    "general_2": "一般数据二级",
    "important": "重要数据",
}

PERSONAL_INFORMATION_LEVELS = {
    "0": "不涉及个人信息",
    "1": "一般个人信息",
    "2": "敏感个人信息",
}

DATA_TYPES = {
    "table": "结构化表格",
    "file": "文件",
    "text": "文本",
    "image": "图像",
    "other": "其他",
}

UPDATE_METHODS = {"全量": "全量更新", "增量": "增量更新"}

# Periodic frequencies are "<n>次/<unit>"; the two fixed values are kept verbatim.
UPDATE_FREQUENCY_UNITS = ["天", "周", "月", "季度", "年"]
UPDATE_FREQUENCY_FIXED = ["不更新", "其他"]

RESOURCE_QUALITY = {
    "01": "高质量",
    "02": "一般质量",
    "03": "低质量",
    "04": "未评估",
}

HIGH_QUALITY_FLAGS = {
    "01": "已认定",
    "02": "自评达标",
    "03": "未评估",
}

AI_READINESS = {
    "01": "可直接训练",
    "02": "需预处理",
    "03": "仅可推理",
    "04": "不适用AI",
}

AI_TASK_TYPES = ["NLP", "CV", "ASR", "推荐", "时序", "多模态", "RL", "其他"]

DATA_MODALITIES = ["文本", "图像", "音频", "视频", "结构化", "多模态"]

SYNTHETIC_DATA = {
    "01": "不包含",
    "02": "部分包含",
    "03": "全部合成",
}

AI_TRAINING_AUTHORIZATION = {
    "01": "允许商用",
    "02": "仅科研",
    "03": "禁止训练",
    "04": "需单独授权",
}

ANNOTATION_STATUSES = {
    "none": "未标注",
    "partial": "部分标注",
    "complete": "已标注",
}

ANNOTATION_TYPES = ["分类标注", "序列标注", "回归标注", "生成式标注", "其他"]

# Data size is described by one of the standard's four representations.
DATA_SIZE_KINDS = {
    "records": "按记录条数（条）",
    "storage": "按存储空间（MB/GB/TB）",
    "coverage": "按覆盖范围",
    "mixed": "混合表示",
}

# Column types accepted by the center (SeaTunnel 2.3.8 scalar types).
COLUMN_TYPES = [
    "string", "boolean", "tinyint", "smallint", "int", "bigint",
    "float", "double", "decimal(p,s)", "bytes", "date", "time", "timestamp",
]

RESOURCE_FORMATS = ["CSV", "TSV", "JSON", "JSONL", "PARQUET", "ORC", "TABLE", "XLSX", "BINARY"]

THEME_LEVEL_1 = {
    "ZA": "综合政务",
    "ZB": "经济管理",
    "ZC": "国土资源、能源",
    "ZD": "工业、交通",
    "ZE": "信息产业",
    "ZF": "城乡建设、环境保护",
    "ZG": "农业、水利",
    "ZH": "财政",
    "ZJ": "商业、贸易",
    "ZK": "旅游、服务业",
    "ZL": "气象、水文、测绘、地震",
    "ZM": "对外事务",
    "ZN": "政法、监察",
    "ZP": "科技、教育",
    "ZQ": "文化、卫生、体育",
    "ZR": "军事、国防",
    "ZS": "劳动、人事",
    "ZT": "民政、社区",
    "ZU": "文秘、行政",
    "ZV": "综合党团",
    "ZW": "综合类",
}

THEME_LEVEL_2 = {
    "ZAA00": "政务综合类",
    "ZAB00": "方针政策",
    "ZAC00": "中共党务",
    "ZAD00": "政府工作",
    "ZAE00": "人大",
    "ZAF00": "政协",
    "ZAG00": "法院",
    "ZAH00": "检察院",
    "ZAJ00": "机构编制",
    "ZAK00": "领导人",
    "ZAL00": "会议、会务",
    "ZAM00": "重大事件",
    "ZBA00": "经济管理综合类",
    "ZBB00": "经济发展计划",
    "ZBC00": "经济管理",
    "ZBD00": "经济体制改革",
    "ZBE00": "经贸管理",
    "ZBF00": "统计",
    "ZBG00": "物价",
    "ZBH00": "工商",
    "ZCA00": "国土资源与能源综合类",
    "ZCB00": "土地",
    "ZCC00": "矿藏",
    "ZCD00": "水资源",
    "ZCE00": "海洋",
    "ZCF00": "煤炭",
    "ZCG00": "石油",
    "ZCH00": "燃料、燃气",
    "ZCJ00": "电力",
    "ZDA00": "工交综合类",
    "ZDB00": "工业",
    "ZDC00": "企业",
    "ZDD00": "交通运输",
    "ZEA00": "信息产业综合类",
    "ZEB00": "通信",
    "ZEC00": "计算机",
    "ZED00": "软件",
    "ZEE00": "网络",
    "ZEF00": "信息技术、信息系统",
    "ZEG00": "邮政",
    "ZFA00": "城乡建设与环境保护综合类",
    "ZFB00": "城乡规划",
    "ZFC00": "城乡建设",
    "ZFD00": "市政工程",
    "ZFE00": "房地产",
    "ZFF00": "环境保护、治理",
    "ZFG00": "环境污染、监测",
    "ZGA00": "农业水利综合类",
    "ZGB00": "农业",
    "ZGC00": "林业",
    "ZGD00": "畜牧业",
    "ZGE00": "副业",
    "ZGF00": "渔业",
    "ZGG00": "水利",
    "ZHA00": "财政综合类",
    "ZHB00": "财政",
    "ZHC00": "税务",
    "ZHD00": "金融",
    "ZHE00": "保险",
    "ZHF00": "审计",
    "ZHG00": "会计",
    "ZJA00": "商贸综合类",
    "ZJB00": "国内贸易",
    "ZJC00": "对外贸易",
    "ZJD00": "物流、仓储",
    "ZJE00": "海关",
    "ZJF00": "检验、检疫",
    "ZKA00": "旅游、服务业综合类",
    "ZKB00": "旅游",
    "ZKC00": "服务业",
    "ZLA00": "气象水文综合类",
    "ZLB00": "气象",
    "ZLC00": "水文",
    "ZLD00": "测绘",
    "ZLE00": "地震",
    "ZMA00": "对外事务综合类",
    "ZMB00": "外交",
    "ZMC00": "外事活动",
    "ZMD00": "国际关系",
    "ZME00": "国际组织",
    "ZMF00": "国际会议",
    "ZNA00": "政法综合类",
    "ZNB00": "公安",
    "ZNC00": "国家安全",
    "ZND00": "监察",
    "ZNE00": "司法",
    "ZPA00": "科教综合类",
    "ZPB00": "科技管理",
    "ZPC00": "科研工作",
    "ZPD00": "知识产权",
    "ZPE00": "技术监督",
    "ZPF00": "教育",
    "ZPG00": "院校管理",
    "ZQA00": "文体综合类",
    "ZQB00": "语言文字",
    "ZQC00": "文学艺术",
    "ZQD00": "文物、考古",
    "ZQE00": "新闻出版",
    "ZQF00": "广播、电影、电视",
    "ZQG00": "医药卫生管理",
    "ZQH00": "医疗保健",
    "ZQJ00": "计划生育",
    "ZQK00": "体育",
    "ZRA00": "军事国防综合类",
    "ZRB00": "国防建设",
    "ZRC00": "军事工作",
    "ZRD00": "军队政治工作",
    "ZRE00": "军事后勤工作",
    "ZRF00": "军事装备工作",
    "ZRG00": "军事技术",
    "ZRH00": "武警",
    "ZSA00": "劳动人事综合类",
    "ZSB00": "人事工作",
    "ZSC00": "劳动就业",
    "ZSD00": "社会保障",
    "ZSE00": "工资职称",
    "ZSF00": "福利待遇",
    "ZTA00": "民政综合类",
    "ZTB00": "民政",
    "ZTC00": "社区",
    "ZUA00": "文秘行政综合类",
    "ZUB00": "文秘工作",
    "ZUC00": "文种",
    "ZUD00": "机要、保密",
    "ZUE00": "档案",
    "ZUF00": "信访工作",
    "ZUG00": "行政事务",
    "ZVA00": "党团综合类",
    "ZVB00": "党派团体",
    "ZVC00": "民族事务",
    "ZVD00": "宗教",
    "ZVE00": "侨务工作",
    "ZVF00": "港澳台工作",
}


def theme_name(code: str) -> str | None:
    """Return the GB/T 21063.4 name for a first- or second-level code."""
    return THEME_LEVEL_2.get(code) or THEME_LEVEL_1.get(code)


def theme_tree() -> list[dict]:
    """Two-level theme options for cascading selects."""
    return [
        {
            "code": code,
            "name": name,
            "children": [
                {"code": child, "name": child_name}
                for child, child_name in THEME_LEVEL_2.items()
                if child[:2] == code
            ],
        }
        for code, name in THEME_LEVEL_1.items()
    ]


def options() -> dict:
    """Every code table, shaped for UI selects and API clients."""
    return {
        "industries": INDUSTRIES,
        "themes": theme_tree(),
        "data_source_types": DATA_SOURCE_TYPES,
        "security_levels": SECURITY_LEVELS,
        "personal_information_levels": PERSONAL_INFORMATION_LEVELS,
        "data_types": DATA_TYPES,
        "update_methods": UPDATE_METHODS,
        "update_frequency": {"units": UPDATE_FREQUENCY_UNITS, "fixed": UPDATE_FREQUENCY_FIXED},
        "resource_quality": RESOURCE_QUALITY,
        "high_quality_flags": HIGH_QUALITY_FLAGS,
        "ai_readiness": AI_READINESS,
        "ai_task_types": AI_TASK_TYPES,
        "data_modalities": DATA_MODALITIES,
        "synthetic_data": SYNTHETIC_DATA,
        "ai_training_authorization": AI_TRAINING_AUTHORIZATION,
        "annotation_statuses": ANNOTATION_STATUSES,
        "annotation_types": ANNOTATION_TYPES,
        "data_size_kinds": DATA_SIZE_KINDS,
        "column_types": COLUMN_TYPES,
        "standard_references": [
            "GB/T 4754-2017 国民经济行业分类",
            "GB/T 21063.4 政务信息资源目录体系 第4部分：政务信息资源分类",
            "数据基础设施 数据目录描述要求（征求意见稿）附录A 表A.1",
            "数据安全技术 数据分类分级规则（报批稿）",
        ],
    }
