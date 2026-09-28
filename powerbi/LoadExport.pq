// Create ExportFolder as a text parameter. Desktop execution is pending.
(TableName as text) as table =>
let
    Dictionary = Json.Document(File.Contents(ExportFolder & "/data_dictionary.json")),
    Fields = Record.Field(Dictionary[tables], TableName),
    Raw = Csv.Document(File.Contents(ExportFolder & "/" & TableName & ".csv"),
        [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Raw, [PromoteAllScalars=true]),
    Nulls = Table.ReplaceValue(Headers, "", null, Replacer.ReplaceValue, Table.ColumnNames(Headers)),
    Types = List.Transform(Record.FieldNames(Fields), each {_, if Record.Field(Fields, _) = "INTEGER" then Int64.Type else type text}),
    Typed = Table.TransformColumnTypes(Nulls, Types, "en-US")
in
    Typed
