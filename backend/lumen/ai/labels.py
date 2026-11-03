"""Zero-shot scene/subject labels.

Each label is matched against an image by comparing the image embedding with the
average embedding of a few English prompts. Labels become tags (source 'ai') named
in Chinese, the product's primary language. Bump ``LABELS_VERSION`` whenever the
vocabulary, prompts or thresholds change: assets are then labeled again.
"""

from __future__ import annotations

from dataclasses import dataclass

LABELS_VERSION = 1

#: A label is applied when its share of a softmax over all labels (using the model's
#: logit scale) reaches this value. Absolute SigLIP probabilities are too low to use
#: once several prompts are averaged, but the ranking is reliable; requiring a clear
#: winner keeps ambiguous photos unlabeled. Calibrated on sample photos.
SHARE_THRESHOLD = 0.25
#: At most this many labels per photo.
MAX_LABELS = 3

TEMPLATES = ["a photo of {}.", "a photograph of {}.", "{}"]


@dataclass(frozen=True)
class Label:
    name: str  # tag name (Chinese)
    prompt: str  # English description used for matching


LABELS: list[Label] = [
    Label("风景", "a landscape"),
    Label("山", "mountains"),
    Label("海滩", "a beach"),
    Label("海", "the sea"),
    Label("湖泊", "a lake"),
    Label("河流", "a river"),
    Label("瀑布", "a waterfall"),
    Label("森林", "a forest"),
    Label("沙漠", "a desert"),
    Label("雪景", "a snowy scene"),
    Label("日出日落", "a sunset or sunrise"),
    Label("夜景", "a city at night"),
    Label("星空", "a starry night sky"),
    Label("天空云彩", "a sky with clouds"),
    Label("城市街道", "a city street"),
    Label("建筑", "architecture"),
    Label("古建筑", "a traditional ancient building"),
    Label("寺庙", "a temple"),
    Label("桥", "a bridge"),
    Label("室内", "an indoor room"),
    Label("人像", "a portrait of a person"),
    Label("合影", "a group photo of people"),
    Label("儿童", "a child"),
    Label("婚礼", "a wedding"),
    Label("宠物", "a pet"),
    Label("猫", "a cat"),
    Label("狗", "a dog"),
    Label("鸟", "a bird"),
    Label("野生动物", "a wild animal"),
    Label("昆虫", "an insect"),
    Label("花卉", "flowers"),
    Label("植物", "plants and leaves"),
    Label("美食", "a dish of food"),
    Label("饮品", "a drink"),
    Label("汽车", "a car"),
    Label("摩托车", "a motorcycle"),
    Label("自行车", "a bicycle"),
    Label("飞机", "an airplane"),
    Label("火车", "a train"),
    Label("船", "a boat"),
    Label("运动", "people playing sports"),
    Label("演出", "a concert or stage performance"),
    Label("节日庆典", "a festival celebration"),
    Label("雨天", "a rainy day"),
    Label("雾", "fog and mist"),
    Label("微距", "a macro close-up"),
    Label("黑白", "a black and white photo"),
    Label("航拍", "an aerial view from a drone"),
    Label("水下", "an underwater scene"),
    Label("街头摄影", "street photography"),
    Label("截图", "a screenshot of a computer or phone screen"),
    Label("文档", "a document with text"),
]


def prompts() -> list[list[str]]:
    """For each label, the prompts whose embeddings are averaged."""
    return [[template.format(label.prompt) for template in TEMPLATES] for label in LABELS]
