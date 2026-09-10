from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator
import uuid

def uid():
    return uuid.uuid4().hex

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Point(Strict):
    t: float = Field(0, ge=0, le=1200)
    x: float = Field(0, ge=-50, le=50)
    y: float = Field(0, ge=-20, le=20)
    z: float = Field(2, ge=-50, le=50)

class Character(Strict):
    id: str = Field(default_factory=uid, pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    name: str = Field(max_length=50)
    voice: str = Field('Chinese (Mandarin)_Reliable_Executive', max_length=150)

class Event(Strict):
    id: str = Field(default_factory=uid, pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    kind: Literal['speech','sfx','ambience','music'] = 'speech'
    character_id: str = ''
    text: str = Field('', max_length=2200)
    original: str = Field('', max_length=2200)
    source_start: int = Field(0, ge=0)
    source_end: int = Field(0, ge=0)
    emotion: Literal['neutral','happy','sad','angry','fearful','disgusted','surprised','calm'] = 'neutral'
    speed: float = Field(1, ge=.5, le=2)
    asset_id: str = Field('', max_length=100)
    anchor_id: str = ''
    placement: Literal['before','after','within','absolute'] = 'after'
    offset: float = Field(0, ge=0, le=1200)
    start: float | None = Field(None, ge=0, le=1200)
    duration: float | None = Field(None, gt=0, le=180)
    gain_db: float = Field(-3, ge=-48, le=6)
    points: list[Point] = Field(default_factory=lambda:[Point()], min_length=1, max_length=32)
    enabled: bool = True

    @model_validator(mode='after')
    def trajectory(self):
        if self.points[0].t != 0 or any(b.t <= a.t for a,b in zip(self.points,self.points[1:])):
            raise ValueError('轨迹必须从0秒开始，时间严格递增')
        return self

class RenderConfig(Strict):
    profile: Literal['H3','H4','H5'] = 'H3'
    room: float = Field(.18, ge=0, le=.6)
    sample_rate: Literal[48000] = 48000

class Project(Strict):
    schema_version: Literal[1] = 1
    id: str = Field(default_factory=uid, pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    revision: int = Field(0, ge=0)
    title: str = Field('未命名场景', min_length=1, max_length=80)
    source: str = Field('', max_length=2000)
    mode: Literal['faithful','drama'] = 'faithful'
    characters: list[Character] = Field(default_factory=list, max_length=16)
    events: list[Event] = Field(default_factory=list, max_length=250)
    render: RenderConfig = Field(default_factory=RenderConfig)
    notes: list[str] = Field(default_factory=list)
    outputs: list[dict] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def references(self):
        chars={c.id for c in self.characters}
        ids=[e.id for e in self.events]
        if len(chars)!=len(self.characters) or len(ids)!=len(set(ids)):
            raise ValueError('角色和事件ID不得重复')
        for e in self.events:
            if e.kind=='speech' and e.character_id not in chars:
                raise ValueError('台词引用了不存在的角色')
            if e.anchor_id and e.anchor_id not in ids:
                raise ValueError('音效锚点不存在')
        return self

class Settings(Strict):
    deepseek_model: str = Field('deepseek-v4-flash', max_length=100)
    tts_model: Literal['speech-2.8-hd','speech-2.8-turbo'] = 'speech-2.8-hd'
    deepseek_key: str = Field('', max_length=500)
    minimax_key: str = Field('', max_length=500)
    input_per_million: float = Field(10, gt=0, le=1000)
    output_per_million: float = Field(30, gt=0, le=1000)
    tts_per_10k: float = Field(3.5, gt=0, le=100)
    rates_confirmed: bool = False
    budget: float = Field(50, gt=0, le=50)
