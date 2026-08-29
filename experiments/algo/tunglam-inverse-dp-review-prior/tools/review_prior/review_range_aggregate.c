#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TABLE_SIZE 131071
#define ID_SIZE 32
#define STAT_COUNT 13

static const char *PARENT_MARKER = "\"parent_asin\": \"";
static const char *TIMESTAMP_MARKER = "\"timestamp\": ";
static const char *VERIFIED_MARKER = "\"verified_purchase\": ";
static const int WINDOW_DAYS[] = {30, 90, 180, 365, 730};
static const uint64_t DAY_MS = 24ULL * 60ULL * 60ULL * 1000ULL;

typedef struct {
    bool used;
    char identifier[ID_SIZE];
    uint64_t stats[STAT_COUNT];
} Entry;

static Entry *table;

static uint64_t hash_identifier(const char *value) {
    uint64_t hash = 1469598103934665603ULL;
    for (const unsigned char *cursor = (const unsigned char *)value; *cursor; cursor++) {
        hash ^= *cursor;
        hash *= 1099511628211ULL;
    }
    return hash;
}

static Entry *find_entry(const char *identifier, bool create) {
    size_t slot = (size_t)(hash_identifier(identifier) % TABLE_SIZE);
    for (size_t attempt = 0; attempt < TABLE_SIZE; attempt++) {
        Entry *entry = &table[slot];
        if (!entry->used) {
            if (!create) {
                return NULL;
            }
            entry->used = true;
            snprintf(entry->identifier, ID_SIZE, "%s", identifier);
            return entry;
        }
        if (strcmp(entry->identifier, identifier) == 0) {
            return entry;
        }
        slot = (slot + 1) % TABLE_SIZE;
    }
    return NULL;
}

static char *find_last_marker(char *line, const char *marker) {
    char *last = NULL;
    char *cursor = line;
    while ((cursor = strstr(cursor, marker)) != NULL) {
        last = cursor;
        cursor++;
    }
    return last;
}

static bool extract_identifier(char *line, char output[ID_SIZE], char **field_end) {
    char *marker = find_last_marker(line, PARENT_MARKER);
    if (marker == NULL) {
        return false;
    }
    char *start = marker + strlen(PARENT_MARKER);
    char *end = strchr(start, '"');
    if (end == NULL || end == start || (size_t)(end - start) >= ID_SIZE) {
        return false;
    }
    size_t length = (size_t)(end - start);
    memcpy(output, start, length);
    output[length] = '\0';
    *field_end = end;
    return true;
}

static bool load_catalog(const char *path) {
    FILE *handle = fopen(path, "r");
    if (handle == NULL) {
        perror("catalog open");
        return false;
    }
    char *line = NULL;
    size_t capacity = 0;
    ssize_t length;
    size_t count = 0;
    while ((length = getline(&line, &capacity, handle)) >= 0) {
        (void)length;
        char identifier[ID_SIZE];
        char *field_end = NULL;
        if (!extract_identifier(line, identifier, &field_end)) {
            free(line);
            fclose(handle);
            fprintf(stderr, "catalog row missing parent_asin\n");
            return false;
        }
        if (find_entry(identifier, true) == NULL) {
            free(line);
            fclose(handle);
            fprintf(stderr, "catalog hash table is full\n");
            return false;
        }
        count++;
    }
    free(line);
    fclose(handle);
    if (count == 0) {
        fprintf(stderr, "catalog is empty\n");
        return false;
    }
    return true;
}

int main(int argc, char **argv) {
    if (argc != 6) {
        fprintf(
            stderr,
            "usage: %s CATALOG REQUEST_START NOMINAL_END CUTOFF_MS IS_FINAL\n",
            argv[0]
        );
        return 2;
    }
    const char *catalog_path = argv[1];
    uint64_t request_start = strtoull(argv[2], NULL, 10);
    uint64_t nominal_end = strtoull(argv[3], NULL, 10);
    uint64_t cutoff_ms = strtoull(argv[4], NULL, 10);
    bool is_final = strcmp(argv[5], "1") == 0;

    table = calloc(TABLE_SIZE, sizeof(Entry));
    if (table == NULL) {
        perror("table allocation");
        return 2;
    }
    if (!load_catalog(catalog_path)) {
        free(table);
        return 2;
    }

    char *line = NULL;
    size_t capacity = 0;
    ssize_t length;
    uint64_t position = request_start;
    uint64_t total_rows = 0;
    uint64_t matched_rows = 0;
    uint64_t malformed_rows = 0;
    uint64_t earliest_timestamp = UINT64_MAX;
    uint64_t latest_timestamp = 0;

    if (request_start > 0) {
        length = getline(&line, &capacity, stdin);
        if (length < 0 || line[length - 1] != '\n') {
            fprintf(stderr, "could not align initial newline boundary\n");
            free(line);
            free(table);
            return 3;
        }
        position += (uint64_t)length;
    }

    while ((length = getline(&line, &capacity, stdin)) >= 0) {
        uint64_t line_start = position;
        position += (uint64_t)length;
        if (line_start > nominal_end) {
            continue;
        }
        if (!is_final && line[length - 1] != '\n') {
            fprintf(stderr, "overlap is too short to complete boundary record\n");
            free(line);
            free(table);
            return 3;
        }

        total_rows++;
        char identifier[ID_SIZE];
        char *field_end = NULL;
        if (!extract_identifier(line, identifier, &field_end)) {
            malformed_rows++;
            continue;
        }
        Entry *entry = find_entry(identifier, false);
        if (entry == NULL) {
            continue;
        }

        char *timestamp_field = strstr(field_end, TIMESTAMP_MARKER);
        char *verified_field = strstr(field_end, VERIFIED_MARKER);
        if (timestamp_field == NULL || verified_field == NULL) {
            malformed_rows++;
            continue;
        }
        uint64_t timestamp = strtoull(
            timestamp_field + strlen(TIMESTAMP_MARKER), NULL, 10
        );
        bool verified = strncmp(
            verified_field + strlen(VERIFIED_MARKER), "true", 4
        ) == 0;

        entry->stats[0]++;
        entry->stats[1] += verified ? 1 : 0;
        if (timestamp > entry->stats[2]) {
            entry->stats[2] = timestamp;
        }
        matched_rows++;
        if (timestamp < earliest_timestamp) {
            earliest_timestamp = timestamp;
        }
        if (timestamp > latest_timestamp) {
            latest_timestamp = timestamp;
        }

        if (timestamp < cutoff_ms) {
            for (size_t window = 0; window < 5; window++) {
                uint64_t start = cutoff_ms - (uint64_t)WINDOW_DAYS[window] * DAY_MS;
                if (timestamp >= start) {
                    size_t raw_index = 3 + 2 * window;
                    entry->stats[raw_index]++;
                    entry->stats[raw_index + 1] += verified ? 1 : 0;
                }
            }
        }
    }
    free(line);

    printf(
        "#summary\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\n",
        total_rows,
        matched_rows,
        malformed_rows,
        earliest_timestamp == UINT64_MAX ? 0 : earliest_timestamp,
        latest_timestamp
    );
    for (size_t slot = 0; slot < TABLE_SIZE; slot++) {
        Entry *entry = &table[slot];
        if (!entry->used || entry->stats[0] == 0) {
            continue;
        }
        printf("%s", entry->identifier);
        for (size_t stat = 0; stat < STAT_COUNT; stat++) {
            printf("\t%" PRIu64, entry->stats[stat]);
        }
        putchar('\n');
    }
    free(table);
    return 0;
}
