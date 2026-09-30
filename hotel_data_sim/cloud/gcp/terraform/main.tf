# GCP — ingesta casi en tiempo real: Pub/Sub → BigQuery (referencia, NO aplicada en este entorno).
# Verificá argumentos y roles contra la documentación vigente del proveedor de Terraform y de
# "BigQuery subscriptions" de Pub/Sub (docs/FUENTES.md). Una BigQuery subscription entrega al menos
# una vez: los duplicados se eliminan en el MERGE de plata (ver ../sql/silver_merge.sql).
variable "project" {}
variable "region" {
  default = "southamerica-east1"
}

provider "google" {
  project = var.project
  region  = var.region
}

resource "google_bigquery_dataset" "bronze" {
  dataset_id = "hotel_bronze"
  location   = var.region
}

resource "google_bigquery_dataset" "silver" {
  dataset_id = "hotel_silver"
  location   = var.region
}

resource "google_bigquery_dataset" "gold" {
  dataset_id = "hotel_gold"
  location   = var.region
}


resource "google_bigquery_table" "bronze_events" {
  dataset_id          = google_bigquery_dataset.bronze.dataset_id
  table_id            = "reservation_events"
  deletion_protection = false
  time_partitioning {
    type  = "DAY"
    field = "publish_time"
  }
  schema = jsonencode([
    { name = "subscription_name", type = "STRING",    mode = "NULLABLE" },
    { name = "message_id",        type = "STRING",    mode = "NULLABLE" },
    { name = "publish_time",      type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "attributes",        type = "JSON",      mode = "NULLABLE" },   # source, hotel_id
    { name = "data",              type = "JSON",      mode = "NULLABLE" },   # payload crudo del sistema fuente
  ])
}

resource "google_pubsub_topic" "reservations" {
  name = "hotel-reservation-events"
}

resource "google_pubsub_topic" "dead_letter" {
  name = "hotel-reservation-events-dlq"
}

data "google_project" "this" {}

# La cuenta de servicio de Pub/Sub necesita escribir en la tabla.
resource "google_bigquery_dataset_iam_member" "pubsub_writer" {
  dataset_id = google_bigquery_dataset.bronze.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_subscription" "to_bigquery" {
  name  = "hotel-reservation-events-bq"
  topic = google_pubsub_topic.reservations.id
  bigquery_config {
    table          = "${var.project}.${google_bigquery_dataset.bronze.dataset_id}.${google_bigquery_table.bronze_events.table_id}"
    write_metadata = true
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 5
  }
  depends_on = [google_bigquery_dataset_iam_member.pubsub_writer]
}
