# SQL Base
## This module is the base implementation for Singer SQL target support.
## Expected usage of this module is to create a class representing your given
## SQL Target which overrides SQLInterface.
#
# Transition
## The given implementation here is in transition as we expand and add various
## targets. As such, there are many private helper functions which are providing
## the real support.
##
## The expectation is that these functions will be added to SQLInterface as we
## better understand how to make adding new targets simpler.
#

from copy import deepcopy

from target_postgres import json_schema
from target_postgres.singer_stream import (
    SINGER_BATCHED_AT,
    SINGER_LEVEL,
    SINGER_PK,
    SINGER_RECEIVED_AT,
    SINGER_SEQUENCE,
    SINGER_SOURCE_PK_PREFIX,
    SINGER_TABLE_VERSION,
    SINGER_VALUE
)

SEPARATOR = '__'


def to_table_schema(path, level, keys, properties):
    for key in keys:
        if not (key,) in properties:
            raise Exception('Unknown key "{}" found for table "{}". Known fields are: {}'.format(
                key, path, properties
            ))

    return {'type': 'TABLE_SCHEMA',
            'path': path,
            'level': level,
            'key_properties': keys,
            'mappings': [],
            'schema': {'type': 'object',
                       'additionalProperties': False,
                       'properties': properties}}


def _mapping_name(field, schema):
    return field + SEPARATOR + json_schema.sql_shorthand(schema)


def _add_singer_columns(schema, key_properties):
    properties = schema['properties']

    if SINGER_RECEIVED_AT not in properties:
        properties[SINGER_RECEIVED_AT] = {
            'type': ['null', 'string'],
            'format': 'date-time'
        }

    if SINGER_SEQUENCE not in properties:
        properties[SINGER_SEQUENCE] = {
            'type': ['null', 'integer']
        }

    if SINGER_TABLE_VERSION not in properties:
        properties[SINGER_TABLE_VERSION] = {
            'type': ['null', 'integer']
        }

    if SINGER_BATCHED_AT not in properties:
        properties[SINGER_BATCHED_AT] = {
            'type': ['null', 'string'],
            'format': 'date-time'
        }

    if len(key_properties) == 0:
        properties[SINGER_PK] = {
            'type': ['string']
        }


def _denest_schema_helper(table_path,
                          table_json_schema,
                          not_null,
                          top_level_schema,
                          key_prop_schemas,
                          subtables,
                          level):
    for prop, item_json_schema in table_json_schema['properties'].items():
        if json_schema.is_object(item_json_schema):
            _denest_schema_helper(table_path + (prop,),
                                  item_json_schema,
                                  not_null,
                                  top_level_schema,
                                  key_prop_schemas,
                                  subtables,
                                  level)
        elif json_schema.is_iterable(item_json_schema):
            _create_subtable(table_path + (prop,),
                             item_json_schema,
                             key_prop_schemas,
                             subtables,
                             level + 1)
        else:
            if not not_null and not json_schema.is_nullable(item_json_schema):
                item_json_schema['type'].append('null')

            top_level_schema[table_path + (prop,)] = item_json_schema


def _create_subtable(table_path, table_json_schema, key_prop_schemas, subtables, level):
    if json_schema.is_object(table_json_schema['items']):
        new_properties = table_json_schema['items']['properties']
    else:
        new_properties = {SINGER_VALUE: table_json_schema['items']}

    key_properties = []
    for pk, item_json_schema in key_prop_schemas.items():
        key_properties.append(SINGER_SOURCE_PK_PREFIX + pk)
        new_properties[SINGER_SOURCE_PK_PREFIX + pk] = item_json_schema

    new_properties[SINGER_SEQUENCE] = {
        'type': ['null', 'integer']
    }

    for i in range(0, level + 1):
        new_properties[SINGER_LEVEL.format(i)] = {
            'type': ['integer']
        }

    new_schema = {'type': ['object'],
                  'properties': new_properties,
                  'level': level,
                  'key_properties': key_properties}

    _denest_schema(table_path, new_schema, key_prop_schemas, subtables, level=level)

    subtables[table_path] = new_schema


def _denest_schema(table_path, table_json_schema, key_prop_schemas, subtables, level=-1):
    new_properties = {}
    for prop, item_json_schema in table_json_schema['properties'].items():

        if json_schema.is_object(item_json_schema):
            not_null = 'null' not in item_json_schema['type']
            _denest_schema_helper(table_path + (prop,),
                                  item_json_schema,
                                  not_null,
                                  new_properties,
                                  key_prop_schemas,
                                  subtables,
                                  level)
        elif json_schema.is_iterable(item_json_schema):
            _create_subtable(table_path + (prop,),
                             item_json_schema,
                             key_prop_schemas,
                             subtables,
                             level + 1)
        else:
            new_properties[(prop,)] = item_json_schema
    table_json_schema['properties'] = new_properties


def _denest_subrecord(table_path,
                      prop_path,
                      parent_record,
                      record,
                      records_map,
                      key_properties,
                      pk_fks,
                      level):
    """"""
    """
    {...}
    """
    for prop, value in record.items():
        """
        str : {...} | [...] | ???None??? | <literal>
        """

        if isinstance(value, dict):
            """
            {...}
            """
            _denest_subrecord(table_path,
                              prop_path + (prop,),
                              parent_record,
                              value,
                              records_map,
                              key_properties,
                              pk_fks,
                              level)
        elif isinstance(value, list):
            """
            [...]
            """
            _denest_records(prop_path + (prop,),
                            value,
                            records_map,
                            key_properties,
                            pk_fks=pk_fks,
                            level=level + 1)
        else:
            """
            None | <literal>
            """
            parent_record[prop_path + (prop,)] = value


def _denest_record(table_path, record, records_map, key_properties, pk_fks, level):
    """"""
    """
    {...}
    """
    denested_record = {}
    for prop, value in record.items():
        """
        str : {...} | [...] | None | <literal>
        """

        if isinstance(value, dict):
            """
            {...}
            """
            _denest_subrecord(table_path + (prop,),
                              (prop,),
                              denested_record,
                              value,
                              records_map,
                              key_properties,
                              pk_fks,
                              level)
        elif isinstance(value, list):
            """
            [...]
            """
            _denest_records(table_path + (prop,),
                            value,
                            records_map,
                            key_properties,
                            pk_fks=pk_fks,
                            level=level + 1)
        elif value is None:  ## nulls mess up nested objects
            """
            None
            """
            continue
        else:
            """
            <literal>
            """
            denested_record[(prop,)] = value

    if table_path not in records_map:
        records_map[table_path] = []
    records_map[table_path].append(denested_record)


def _denest_records(table_path, records, records_map, key_properties, pk_fks=None, level=-1):
    row_index = 0
    """
    [{...} ...] | [[...] ...] | [literal ...]
    """
    for record in records:
        if pk_fks:
            record_pk_fks = pk_fks.copy()
            record_pk_fks[SINGER_LEVEL.format(level)] = row_index

            if not isinstance(record, dict):
                """
                [...] | literal
                """
                record = {SINGER_VALUE: record}

            for key, value in record_pk_fks.items():
                record[key] = value
            row_index += 1
        else:  ## top level
            record_pk_fks = {}
            for key in key_properties:
                record_pk_fks[SINGER_SOURCE_PK_PREFIX + key] = record[key]
            if SINGER_SEQUENCE in record:
                record_pk_fks[SINGER_SEQUENCE] = record[SINGER_SEQUENCE]

        """
        {...}
        """
        _denest_record(table_path, record, records_map, key_properties, record_pk_fks, level)


class SQLInterface:
    """
    Generic interface for handling SQL Targets in Singer.

    Provides reasonable defaults for:
    - nested schemas -> traditional SQL Tables and Columns
    - nested records -> traditional SQL Table rows

    Expected usage for use with your given target is to:
    - override all public _non-helper_ functions
    - use all public _helper_ functions inside of your _non-helper_ functions

    Function Syntax:
    - `_...` prefix : Private function
    - `..._helper` suffix : Helper function
    """

    IDENTIFIER_FIELD_LENGTH = NotImplementedError('`IDENTIFIER_FIELD_LENGTH` not implemented.')

    def _get_streamed_table_schemas(self, schema, key_properties):
        """
        Given a `schema` and `key_properties` return the denested/flattened TABLE_SCHEMA of
        the root table and each sub table.

        :param schema: SingerStreamSchema
        :param key_properties: [string, ...]
        :return: [TABLE_SCHEMA(denested_streamed_schema_0), ...]
        """
        root_table_schema = json_schema.simplify(schema)

        _add_singer_columns(root_table_schema, key_properties)

        subtables = {}
        key_prop_schemas = {}
        for key in key_properties:
            key_prop_schemas[key] = schema['properties'][key]
        _denest_schema(tuple(), root_table_schema, key_prop_schemas, subtables)

        ret = [to_table_schema(tuple(), None, key_properties, root_table_schema['properties'])]
        for path, schema in subtables.items():
            ret.append(to_table_schema(path, schema['level'], schema['key_properties'], schema['properties']))

        return ret

    def get_table_schema(self, connection, path, name):
        """
        Fetch the `table_schema` for `name`.

        :param connection: remote connection, type left to be determined by implementing class
        :param path: (string, ...)
        :param name: string
        :return: TABLE_SCHEMA(remote)
        """
        raise NotImplementedError('`get_table_schema` not implemented.')

    def is_table_empty(self, connection, name):
        """
        Returns True when given table name has no rows.

        :param connection: remote connection, type left to be determined by implementing class
        :param name: string
        :return: boolean
        """
        raise NotImplementedError('`is_table_empty` not implemented.')

    def canonicalize_identifier(self, name):
        """
        Given a SQL Identifier `name`, attempt to serialize it to an acceptable name for remote.
        NOTE: DOES NOT handle collision support, nor identifier length/truncation support.

        :param name: string
        :return: string
        """
        raise NotImplementedError('`canonicalize_identifier` not implemented.')

    def _canonicalize_identifier(self, name, schema, existing_columns_raw_names, existing_columns):
        """"""
        raw_canonicalized_column_name = self.canonicalize_identifier(name)
        canonicalized_column_name = raw_canonicalized_column_name[:self.IDENTIFIER_FIELD_LENGTH]
        canonicalized_typed_column_name = _mapping_name(
            raw_canonicalized_column_name[:self.IDENTIFIER_FIELD_LENGTH - 3], schema)

        ## NAME IS ALREADY CANONICALIZED
        if name == raw_canonicalized_column_name \
                and raw_canonicalized_column_name == canonicalized_column_name:
            return canonicalized_column_name, canonicalized_typed_column_name

        ## COLUMN WILL BE SPLIT
        if name in existing_columns_raw_names:
            return canonicalized_column_name, canonicalized_typed_column_name

        i = 0
        ## NAME COLLISION
        while (canonicalized_column_name in existing_columns
               or canonicalized_typed_column_name in existing_columns):
            i += 1
            suffix = SEPARATOR + str(i)
            canonicalized_column_name = raw_canonicalized_column_name[
                                        :self.IDENTIFIER_FIELD_LENGTH - len(suffix)] + suffix
            canonicalized_typed_column_name = _mapping_name(
                raw_canonicalized_column_name[:self.IDENTIFIER_FIELD_LENGTH - 3 - len(suffix)], schema) + suffix

            # TODO: logger warn
            ##raise Exception(
            ##    'NAME COLLISION: Cannot handle merging column `{}` (canonicalized as: `{}`, canonicalized with type as: `{}`) in table `{}`.'.format(
            ##        raw_column_name,
            ##        canonicalized_column_name,
            ##        canonicalized_typed_column_name,
            ##        table_name
            ##    ))

        return canonicalized_column_name, canonicalized_typed_column_name

    def add_table(self, connection, schema, metadata):
        """
        Create the remote table schema.

        :param connection: remote connection, type left to be determined by implementing class
        :param schema: TABLE_SCHEMA(local) definition for table to be created
        :param metadata: additional metadata needed by implementing class
        :return: None
        """
        raise NotImplementedError('`add_table` not implemented.')

    def add_key_properties(self, connection, table_name, key_properties):
        """

        :param connection: remote connection, type left to be determined by implementing class
        :param table_name: string
        :param key_properties: [string, ...]
        :return: None
        """
        raise NotImplementedError('`add_key_properties` not implemented.')

    def add_table_mapping_helper(self, from_path, table_mappings):
        """

        :param from_path:
        :param table_mappings:
        :return: (boolean, string)
        """
        from_to = dict([(tuple(mapping['from']), mapping['to']) for mapping in table_mappings])

        ## MAPPING EXISTS
        if from_path in from_to:
            return {'exists': True, 'to': from_to[from_path]}

        to_from = dict([(v, k) for k, v in from_to.items()])

        name = SEPARATOR.join(from_path)

        raw_canonicalized_name = self.canonicalize_identifier(name)
        canonicalized_name = raw_canonicalized_name[:self.IDENTIFIER_FIELD_LENGTH]

        i = 0
        ## NAME COLLISION
        while canonicalized_name in to_from:
            i += 1
            suffix = SEPARATOR + str(i)
            canonicalized_name = raw_canonicalized_name[
                                 :self.IDENTIFIER_FIELD_LENGTH - len(suffix)] + suffix

            # TODO: logger warn
            ##raise Exception(
            ##    'NAME COLLISION: Cannot handle merging column `{}` (canonicalized as: `{}`, canonicalized with type as: `{}`) in table `{}`.'.format(
            ##        raw_column_name,
            ##        canonicalized_column_name,
            ##        canonicalized_typed_column_name,
            ##        table_name
            ##    ))

        return {'exists': False, 'to': canonicalized_name}

    def add_table_mapping(self, connection, from_path, metadata):
        """
        Given a full path to a table, `from_path`, add a table mapping to the canonicalized name.

        :param connection: remote connection, type left to be determined by implementing class
        :param from_path: (string, ...)
        :return: None
        """
        raise NotImplementedError('`add_table_mapping` not implemented.')

    def add_column(self, connection, table_name, name, schema):
        """
        Add column `name` in `table_name` with `schema`.

        :param connection: remote connection, type left to be determined by implementing class
        :param table_name: string
        :param name: string
        :param schema: JSON Object Schema
        :return: None
        """
        raise NotImplementedError('`add_column` not implemented.')

    def drop_column(self, connection, table_name, name):
        """
        Drop column `name` in `table_name`.

        :param connection: remote connection, type left to be determined by implementing class
        :param table_name: string
        :param name: string
        :return: None
        """
        raise NotImplementedError('`add_column` not implemented.')

    def migrate_column(self, connection, table_name, from_column, to_column):
        """
        Migrate data `from_column` in `table_name` `to_column`.

        :param connection: remote connection, type left to be determined by implementing class
        :param table_name: string
        :param from_column: string
        :param to_column: string
        :return: None
        """
        raise NotImplementedError('`migrate_column` not implemented.')

    def make_column_nullable(self, connection, table_name, name):
        """
        Update column `name` in `table_name` to accept `null` values.

        :param connection: remote connection, type left to be determined by implementing class
        :param table_name: string
        :param name: string
        :return: None
        """
        raise NotImplementedError('`make_column_nullable` not implemented.')

    def add_column_mapping(self, connection, table_name, name, mapped_name, schema):
        """
        Given column `name` add a column mapping to `mapped_name` for `schema`. A column mapping is an entry
        in the TABLE_SCHEMA which reads:

        {...
         'mappings': {...
           `mapped_name`: {'type': `json_schema.get_type(schema)`,
                           'from': `name`}
         }
         ...}

        :param connection: remote connection, type left to be determined by implementing class
        :param table_name: string
        :param name: string
        :param mapped_name: string
        :param schema: JSON Object Schema
        :return: None
        """
        raise NotImplementedError('`add_column_mapping` not implemented.')

    def drop_column_mapping(self, connection, table_name, name):
        """
        Given column mapping `name`, remove from the TABLE_SCHEMA(remote).

        :param connection: remote connection, type left to be determined by implementing class
        :param table_name: string
        :param name: string
        :return: None
        """
        raise NotImplementedError('`remove_column_mapping` not implemented.')

    def _get_mapping(self, existing_schema, field, schema):
        if 'mappings' not in existing_schema:
            return None

        inverted_mappings = dict([((mapping['from'],
                                    json_schema.sql_shorthand(mapping)),
                                   to_field)
                                  for (to_field, mapping) in existing_schema['mappings'].items()])

        return inverted_mappings.get(
            (field,
             json_schema.sql_shorthand(schema)),
            None)

    def upsert_table_helper(self, connection, schema, metadata):
        """
        Upserts the `schema` to remote by:
        - creating table if necessary
        - adding columns
        - adding column mappings
        - migrating data from old columns to new, etc.

        :param connection: remote connection, type left to be determined by implementing class
        :param schema: TABLE_SCHEMA(local)
        :param metadata: additional information necessary for downstream operations
        :return: TABLE_SCHEMA(remote)
        """
        table_path = schema['path']

        table_name = self.add_table_mapping(connection, table_path, metadata)

        existing_schema = self.get_table_schema(connection, table_path, table_name)

        if existing_schema is None:
            self.add_table(connection, table_name, metadata)
            existing_schema = self.get_table_schema(connection, table_path, table_name)

        self.add_key_properties(connection, table_name, schema.get('key_properties', None))

        new_columns = schema['schema']['properties']
        existing_columns = existing_schema['schema']['properties']
        existing_columns_raw_names = [v['from'] for v in existing_schema.get('mappings', {}).values()]
        table_empty = self.is_table_empty(connection, table_name)

        ## Only process columns which have single, nullable, types
        single_type_columns = []
        for raw_column_name__or__path, column_schema in new_columns.items():
            raw_column_name = raw_column_name__or__path
            if isinstance(raw_column_name__or__path, tuple):
                raw_column_name = SEPARATOR.join(raw_column_name__or__path)

            single_type_column_schema = deepcopy(column_schema)
            column_types = json_schema.get_type(single_type_column_schema)
            make_nullable = json_schema.is_nullable(column_schema)

            for type in column_types:
                if type == json_schema.NULL:
                    continue

                single_type_column_schema['type'] = [type]

                if make_nullable:
                    single_type_columns.append((raw_column_name, json_schema.make_nullable(single_type_column_schema)))
                else:
                    single_type_columns.append((raw_column_name, single_type_column_schema))

        ## Process new columns against existing
        for raw_column_name, column_schema in single_type_columns:
            canonicalized_column_name, canonicalized_typed_column_name = self._canonicalize_identifier(
                raw_column_name, column_schema, existing_columns_raw_names, existing_columns
            )
            nullable_column_schema = json_schema.make_nullable(column_schema)

            ## EXISTING COLUMNS
            if canonicalized_column_name in existing_columns \
                    and json_schema.to_sql(column_schema) \
                    == json_schema.to_sql(existing_columns[canonicalized_column_name]):
                pass
            ###
            elif canonicalized_typed_column_name in existing_columns \
                    and json_schema.to_sql(column_schema) \
                    == json_schema.to_sql(existing_columns[canonicalized_typed_column_name]):
                pass
            ###
            elif canonicalized_column_name in existing_columns \
                    and json_schema.to_sql(nullable_column_schema) \
                    == json_schema.to_sql(existing_columns[canonicalized_column_name]):
                pass
            ###
            elif canonicalized_typed_column_name in existing_columns \
                    and json_schema.to_sql(nullable_column_schema) \
                    == json_schema.to_sql(existing_columns[canonicalized_typed_column_name]):
                pass

            ## NULL COMPATIBILITY
            elif canonicalized_column_name in existing_columns \
                    and json_schema.to_sql(nullable_column_schema) == json_schema.to_sql(
                json_schema.make_nullable(existing_columns[canonicalized_column_name])):

                ## MAKE NULLABLE
                self.make_column_nullable(connection,
                                          table_name,
                                          canonicalized_column_name)
                existing_columns[canonicalized_column_name] = json_schema.make_nullable(
                    existing_columns[canonicalized_column_name])

            ## FIRST DUPLICATE TYPE
            elif canonicalized_column_name in existing_columns:

                if self._get_mapping(existing_schema, raw_column_name, existing_columns[canonicalized_column_name]):
                    self.drop_column_mapping(connection, table_name, canonicalized_column_name)

                ## column_name -> column_name__<current-type>, column_name__<new-type>
                existing_column_mapping = _mapping_name(canonicalized_column_name,
                                                        existing_columns[canonicalized_column_name])

                ## Update existing properties
                existing_columns[existing_column_mapping] = json_schema.make_nullable(
                    existing_columns[canonicalized_column_name])
                existing_columns[canonicalized_typed_column_name] = json_schema.make_nullable(column_schema)

                ## Add new columns
                ### NOTE: all migrated columns will be nullable and remain that way

                #### Table Metadata
                self.add_column_mapping(connection, table_name, raw_column_name,
                                        existing_column_mapping,
                                        existing_columns[existing_column_mapping])
                self.add_column_mapping(connection, table_name, raw_column_name,
                                        canonicalized_typed_column_name,
                                        existing_columns[canonicalized_typed_column_name])

                #### Columns
                self.add_column(connection,
                                table_name,
                                existing_column_mapping,
                                existing_columns[existing_column_mapping])

                self.add_column(connection,
                                table_name,
                                canonicalized_typed_column_name,
                                existing_columns[canonicalized_typed_column_name])

                ## Migrate existing data
                self.migrate_column(connection,
                                    table_name,
                                    canonicalized_column_name,
                                    existing_column_mapping)

                ## Drop existing column
                self.drop_column(connection,
                                 table_name,
                                 canonicalized_column_name)

                ## Remove column (field) from existing_properties
                del existing_columns[canonicalized_column_name]

            ## MULTI DUPLICATE TYPE
            elif raw_column_name in existing_columns_raw_names:

                ## Add new column
                self.add_column_mapping(connection, table_name, raw_column_name,
                                        canonicalized_typed_column_name,
                                        nullable_column_schema)
                existing_columns_raw_names.append(canonicalized_typed_column_name)

                self.add_column(connection,
                                table_name,
                                canonicalized_typed_column_name,
                                nullable_column_schema)

                ## Update existing properties
                existing_columns[canonicalized_typed_column_name] = nullable_column_schema

            ## NEW COLUMN, VALID NAME, EMPTY TABLE
            elif canonicalized_column_name == raw_column_name and table_empty:

                self.add_column(connection,
                                table_name,
                                canonicalized_column_name,
                                column_schema)
                existing_columns[canonicalized_column_name] = column_schema

            ## NEW COLUMN, VALID NAME
            #             self.logger.warning('Forcing new column `{}.{}.{}` to be nullable due to table not empty.'.format(
            #                 self.postgres_schema,
            #                 table_name,
            #                 column_name))
            elif canonicalized_column_name == raw_column_name:

                self.add_column(connection,
                                table_name,
                                canonicalized_column_name,
                                nullable_column_schema)
                existing_columns[canonicalized_column_name] = nullable_column_schema

            ## NEW COLUMN, INVALID NAME, EMPTY TABLE
            elif canonicalized_column_name != raw_column_name and table_empty:

                self.add_column_mapping(connection, table_name, raw_column_name, canonicalized_column_name,
                                        column_schema)
                existing_columns_raw_names.append(canonicalized_column_name)
                self.add_column(connection,
                                table_name,
                                canonicalized_column_name,
                                column_schema)
                existing_columns[canonicalized_column_name] = column_schema

            ## NEW COLUMN, INVALID NAME
            elif canonicalized_column_name != raw_column_name:

                self.add_column_mapping(connection, table_name, raw_column_name, canonicalized_column_name,
                                        nullable_column_schema)
                existing_columns_raw_names.append(canonicalized_column_name)
                self.add_column(connection,
                                table_name,
                                canonicalized_column_name,
                                nullable_column_schema)
                existing_columns[canonicalized_column_name] = nullable_column_schema

            ## UNKNOWN
            else:
                raise Exception(
                    'UNKNOWN: Cannot handle merging column `{}` (canonicalized as: `{}`, canonicalized with type as: `{}`) in table `{}`.'.format(
                        raw_column_name,
                        canonicalized_column_name,
                        canonicalized_typed_column_name,
                        table_name
                    ))

        return self.get_table_schema(connection, table_path, table_name)

    def _get_streamed_table_records(self, key_properties, records):
        """
        Flatten the given `records` into `table_records`.
        Maintains `key_properties`.
        into `table_records`.

        :param key_properties: [string, ...]
        :param records: [{...}, ...]
        :return: {TableName string: [{...}, ...],
                  ...}
        """

        records_map = {}
        _denest_records(tuple(),
                        records,
                        records_map,
                        key_properties)

        return records_map

    def _get_table_batches(self, schema, key_properties, records):
        """
        Given the streamed schema, and records, get all table schemas and records and prep them
        in a `table_batch`.

        :param schema: SingerStreamSchema
        :param key_properties: [string, ...]
        :param records: [{...}, ...]
        :return: [{'streamed_schema': TABLE_SCHEMA(local),
                   'records': [{...}, ...]
        """

        table_schemas = self._get_streamed_table_schemas(schema,
                                                         key_properties)

        table_records = self._get_streamed_table_records(key_properties,
                                                         records)
        writeable_batches = []
        for table_json_schema in table_schemas:
            writeable_batches.append({'streamed_schema': table_json_schema,
                                      'records': table_records.get(table_json_schema['path'], [])})

        return writeable_batches

    def _serialize_table_record_field_name(self, remote_schema, streamed_schema, path):
        """
        Returns the appropriate remote field (column) name for `field`.

        :param remote_schema: TABLE_SCHEMA(remote)
        :param streamed_schema: TABLE_SCHEMA(local)
        :param field: string
        :return: string
        """

        field = SEPARATOR.join(path)

        return self._get_mapping(remote_schema,
                                 field,
                                 streamed_schema['schema']['properties'][path]) \
               or field

    def serialize_table_record_null_value(
            self, remote_schema, streamed_schema, field, value):
        """
        Returns the serialized version of `value` which is appropriate for the target's null
        implementation.

        :param remote_schema: TABLE_SCHEMA(remote)
        :param streamed_schema: TABLE_SCHEMA(local)
        :param field: string
        :param value: literal
        :return: literal
        """
        raise NotImplementedError('`parse_table_record_serialize_null_value` not implemented.')

    def serialize_table_record_datetime_value(
            self, remote_schema, streamed_schema, field, value):
        """
        Returns the serialized version of `value` which is appropriate  for the target's datetime
        implementation.

        :param remote_schema: TABLE_SCHEMA(remote)
        :param streamed_schema: TABLE_SCHEMA(local)
        :param field: string
        :param value: literal
        :return: literal
        """

        raise NotImplementedError('`parse_table_record_serialize_datetime_value` not implemented.')

    def _serialize_table_records(
            self, remote_schema, streamed_schema, records):
        """
        Parse the given table's `records` in preparation for persistence to the remote target.

        Base implementation returns a list of dictionaries, where _every_ dictionary has the
        same keys as `remote_schema`'s properties.

        :param remote_schema: TABLE_SCHEMA(remote)
        :param streamed_schema: TABLE_SCHEMA(local)
        :param records: [{...}, ...]
        :return: [{...}, ...]
        """

        datetime_paths = [k for k, v in streamed_schema['schema']['properties'].items()
                          if v.get('format') == 'date-time']

        default_paths = {k: v.get('default') for k, v in streamed_schema['schema']['properties'].items()
                         if v.get('default') is not None}

        ## Get the default NULL value so we can assign row values when value is _not_ NULL
        NULL_DEFAULT = self.serialize_table_record_null_value(remote_schema, streamed_schema, None, None)

        serialized_rows = []

        remote_fields = set(remote_schema['schema']['properties'].keys())
        default_row = dict([(field, NULL_DEFAULT) for field in remote_fields])

        paths = streamed_schema['schema']['properties'].keys()
        for record in records:

            row = deepcopy(default_row)

            for path in paths:
                value = record.get(path, None)

                ## Serialize fields which are not present but have default values set
                if path in default_paths \
                        and value is None:
                    value = default_paths[path]

                ## Serialize datetime to compatible format
                if path in datetime_paths \
                        and value is not None:
                    value = self.serialize_table_record_datetime_value(remote_schema, streamed_schema, path,
                                                                       value)

                ## Serialize NULL default value
                value = self.serialize_table_record_null_value(remote_schema, streamed_schema, path, value)

                field_name = self._serialize_table_record_field_name(remote_schema, streamed_schema, path)

                if field_name in remote_fields \
                        and (not field_name in row
                             or row[field_name] == NULL_DEFAULT):
                    row[field_name] = value

            serialized_rows.append(row)

        return serialized_rows

    def write_table_batch(self, connection, table_batch, metadata):
        """
        Update the remote for given table's schema, and write records. Returns the number of
        records persisted.

        :param connection: remote connection, type left to be determined by implementing class
        :param table_batch: {'remote_schema': TABLE_SCHEMA(remote),
                             'records': [{...}, ...]}
        :param metadata: additional metadata needed by implementing class
        :return: integer
        """
        raise NotImplementedError('`write_table_batch` not implemented.')

    def write_batch_helper(self, connection, root_table_name, schema, key_properties, records, metadata):
        """
        Write all `table_batch`s associated with the given `schema` and `records` to remote.

        :param connection: remote connection, type left to be determined by implementing class
        :param root_table_name: string
        :param schema: SingerStreamSchema
        :param key_properties: [string, ...]
        :param records: [{...}, ...]
        :param metadata: additional metadata needed by implementing class
        :return: {'records_persisted': int,
                  'rows_persisted': int}
        """
        records_persisted = len(records)
        rows_persisted = 0
        for table_batch in self._get_table_batches(schema, key_properties, records):
            table_batch['streamed_schema']['path'] = (root_table_name,) + table_batch['streamed_schema']['path']
            remote_schema = self.upsert_table_helper(connection,
                                                     table_batch['streamed_schema'],
                                                     metadata)
            rows_persisted += self.write_table_batch(
                connection,
                {'remote_schema': remote_schema,
                 'records': self._serialize_table_records(remote_schema,
                                                          table_batch['streamed_schema'],
                                                          table_batch['records'])},
                metadata)

        return {
            'records_persisted': records_persisted,
            'rows_persisted': rows_persisted
        }

    def write_batch(self, stream_buffer):
        """
        Persist `stream_buffer.records` to remote.

        :param stream_buffer: SingerStreamBuffer
        :return: {'records_persisted': int,
                  'rows_persisted': int}
        """
        raise NotImplementedError('`write_batch` not implemented.')

    def activate_version(self, stream_buffer, version):
        """
        Activate the given `stream_buffer`'s remote to `version`

        :param stream_buffer: SingerStreamBuffer
        :param version: integer
        :return: boolean
        """
        raise NotImplementedError('`activate_version` not implemented.')
