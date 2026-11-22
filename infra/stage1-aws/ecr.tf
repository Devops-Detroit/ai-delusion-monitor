resource "aws_ecr_repository" "this" {
  for_each             = local.images
  name                 = "${var.name}/${each.key}"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # lets `terraform destroy` remove repos that still hold images

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 5 most recent images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }
      action       = { type = "expire" }
    }]
  })
}

# Bootstrap guard: these lookups exist only when create_service = true. They
# fail the plan if an image has not been pushed. The task definition then pins
# each container to the image digest, so changing a tag cannot change a running task.
data "aws_ecr_image" "this" {
  for_each        = var.create_service ? local.images : toset([])
  repository_name = aws_ecr_repository.this[each.key].name
  image_tag       = var.image_tag
}
