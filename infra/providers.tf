provider "aws" {
  region = var.region

  # Every AWS resource carries these tags (system design §8.1 rule 2), which
  # is also how scripts/verify-zero.sh finds anything left behind.
  default_tags {
    tags = {
      project = "speakquest"
      env     = var.env
      owner   = var.owner
    }
  }
}

# The token comes from the shell (VERCEL_API_TOKEN); it is never written to a
# file in this repository. With enable_frontend = false the provider makes no
# API calls.
provider "vercel" {
  team = var.vercel_team_id != "" ? var.vercel_team_id : null
}
