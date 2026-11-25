# The gateway through which the harness reaches the four tools, as MCP. A
# caller signs its request with IAM credentials and needs
# bedrock-agentcore:InvokeGateway on this gateway; see
# docs/decisions/0005-gateway-with-iam-inbound-and-a-role-for-one-function.md.
resource "aws_bedrockagentcore_gateway" "tools" {
  name            = "${local.name_prefix}-gateway"
  description     = "Exposes the four Fareguard tools to the harness."
  protocol_type   = "MCP"
  authorizer_type = "AWS_IAM"
  role_arn        = aws_iam_role.gateway.arn
}

locals {
  # The target name is the prefix of every tool name the harness sees:
  # "fareguard___<tool>". The hook and the tools handler remove it.
  gateway_target_name = "fareguard"

  # The tools and their arguments, as fareguard.tools.dispatch defines them.
  # Every argument is a required string. A description says what the tool
  # does and states no rule or limit: the rules live in the hook.
  gateway_tools = [
    {
      name        = "read_ledger"
      description = "Returns the queued discs, what was spent on each, the spend of the current month and the most recent ledger events."
      arguments   = []
    },
    {
      name        = "list_pending"
      description = "Returns the approval requests that are waiting for a person's decision."
      arguments   = []
    },
    {
      name        = "request_approval"
      description = "Asks a person to approve the launch of one disc. Returns the reference of the request and the estimated cost."
      arguments = [
        { name = "disc_id", description = "The id of the disc." },
      ]
    },
    {
      name        = "launch_job"
      description = "Launches the job of one disc under an approval."
      arguments = [
        { name = "disc_id", description = "The id of the disc." },
        { name = "approval_ref", description = "The reference of the approval request." },
      ]
    },
  ]
}

resource "aws_bedrockagentcore_gateway_target" "fareguard" {
  name               = local.gateway_target_name
  description        = "The tools Lambda function."
  gateway_identifier = aws_bedrockagentcore_gateway.tools.gateway_id

  # The gateway invokes the function as its own role.
  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.tools.arn

        tool_schema {
          dynamic "inline_payload" {
            for_each = local.gateway_tools

            content {
              name        = inline_payload.value.name
              description = inline_payload.value.description

              input_schema {
                type = "object"

                dynamic "property" {
                  for_each = inline_payload.value.arguments

                  content {
                    name        = property.value.name
                    description = property.value.description
                    type        = "string"
                    required    = true
                  }
                }
              }
            }
          }
        }
      }
    }
  }

  # AgentCore must be able to assume the role, and the role to invoke the
  # function, before the target is created; see the pause in iam_gateway.tf.
  depends_on = [time_sleep.gateway_role_propagation]
}
