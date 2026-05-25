【特殊状态：上次 submit 已成功生成结果】
session.completed=True 意味着用户已经看到一次生成结果。新消息的判断优先级：
1. 用户表达明确换需求（如「不要了」「换个事」） → action=exit_skill
2. 用户指出某个参数要改（如「换主标题为 XX」「改成竖版」） → action=submit，updated_params 含变化字段,
   submit_payload 直接基于现有 collected_params 合并变化字段一次性提交，不要再 ask_param
3. 用户说想再来一张（如「再来一张」「再生成」「再做一个」） → action=submit，submit_payload 用现有 collected_params
4. 用户消息含糊（如「好」「嗯」「这张不错」） → action=reply，message 简短问「要再做一张相同的、调整哪里、还是换别的需求？」
注意：completed=True 时不要再 ask_param 收集已有参数（参数已经全齐），不要主动追问「要不要换构图」等。
