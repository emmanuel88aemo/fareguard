# The guardrail the hook function applies, through the ApplyGuardrail API, to
# text on its way to the model: what the caller sent and what a tool returned.
# It is not attached to the harness or to a model; see
# docs/decisions/0006-guardrail-applied-by-the-hook.md.
#
# It is a second layer. No rule depends on it: a launch is judged by the hook
# and by the tools whatever the model was told.
#
# It has one policy, the prompt attack filter, and no denied topic: a topic
# could not tell a launch with an approval from one without. See
# docs/decisions/0011-guardrail-with-the-prompt-attack-filter-only.md.
resource "aws_bedrock_guardrail" "hook" {
  name        = "${local.name_prefix}-guardrail"
  description = "Screens the text that reaches the Fareguard agent for prompt attacks."

  # Fixed and short. The hook never passes them on: it answers with its own
  # sentence for rule R7.
  blocked_input_messaging   = "Blocked by the Fareguard guardrail."
  blocked_outputs_messaging = "Blocked by the Fareguard guardrail."

  # The prompt attack filter judges input only, so its output strength is NONE.
  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      input_action    = "BLOCK"
      input_enabled   = true
      output_strength = "NONE"
    }
  }
}

# A published version is a fixed copy of the guardrail: the hook applies this
# number, never the working draft, so what it applies cannot change under it.
resource "aws_bedrock_guardrail_version" "hook" {
  guardrail_arn = aws_bedrock_guardrail.hook.guardrail_arn
  description   = "The version the hook function applies."

  lifecycle {
    # A version does not follow its guardrail. Any change to the guardrail
    # publishes a new one, and the old one is deleted only after the hook
    # function has been given the new number.
    replace_triggered_by  = [aws_bedrock_guardrail.hook]
    create_before_destroy = true
  }
}
