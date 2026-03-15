variable "db_url" {
  type    = string
  default = "postgres://chatagent:chatagent@127.0.0.1:7753/chatagent?sslmode=disable"
}

env "local" {
  url = var.db_url

  migration {
    dir = "file://db/migrations"
  }

  format {
    migrate {
      diff = "{{ sql . \"  \" }}"
    }
  }
}
