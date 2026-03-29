using System.CommandLine;
using System.Text.Json;
using MiniMaxAIDocx.Core.Validation;

namespace MiniMaxAIDocx.Core.Commands;

public static class ValidateCommand
{
    public static Command Create()
    {
        var inputOption = new Option<string>("--input") { Description = "DOCX file to validate", Required = true };
        var xsdOption = new Option<string>("--xsd") { Description = "XSD schema path for XML validation" };
        var businessOption = new Option<bool>("--business") { Description = "Run business rule validation" };
        var gateCheckOption = new Option<string>("--gate-check") { Description = "Template DOCX for gate-check validation" };
        var jsonOption = new Option<bool>("--json") { Description = "Output results as JSON" };

        var cmd = new Command("validate", "Validate DOCX structure and content")
        {
            inputOption, xsdOption, businessOption, gateCheckOption, jsonOption
        };

        cmd.SetAction((parseResult) =>
        {
            var input = parseResult.GetValue(inputOption)!;
            var xsd = parseResult.GetValue(xsdOption);
            var business = parseResult.GetValue(businessOption);
            var gateCheck = parseResult.GetValue(gateCheckOption);
            var asJson = parseResult.GetValue(jsonOption);

            if (!File.Exists(input))
            {
                Console.Error.WriteLine($"File not found: {input}");
                return;
            }

            var combinedResult = new ValidationResult();
            GateCheckResult? gateResult = null;

            if (xsd != null)
            {
                var xsdValidator = new XsdValidator();
                combinedResult.Merge(xsdValidator.Validate(input, xsd));
            }

            if (business)
            {
                var bizValidator = new BusinessRuleValidator();
                combinedResult.Merge(bizValidator.Validate(input));
            }

            if (gateCheck != null)
            {
                var gateValidator = new GateCheckValidator();
                gateResult = gateValidator.Validate(input, gateCheck);
            }

            if (asJson)
            {
                var output = new
                {
                    isValid = combinedResult.IsValid && (gateResult?.Passed ?? true),
                    errors = combinedResult.Errors,
                    warnings = combinedResult.Warnings,
                    gateCheck = gateResult == null ? null : new
                    {
                        passed = gateResult.Passed,
                        violations = gateResult.Violations
                    }
                };
                Console.WriteLine(JsonSerializer.Serialize(output, new JsonSerializerOptions { WriteIndented = true }));
            }
            else
            {
                if (combinedResult.Errors.Count > 0)
                {
                    Console.WriteLine($"ERRORS ({combinedResult.Errors.Count}):");
                    foreach (var e in combinedResult.Errors)
                        Console.WriteLine($"  [{e.Severity}] {e.Message}" + (e.LineNumber > 0 ? $" (line {e.LineNumber}:{e.LinePosition})" : ""));
                }

                if (combinedResult.Warnings.Count > 0)
                {
                    Console.WriteLine($"WARNINGS ({combinedResult.Warnings.Count}):");
                    foreach (var w in combinedResult.Warnings)
                        Console.WriteLine($"  [{w.Severity}] {w.Message}");
                }

                if (gateResult != null)
                {
                    Console.WriteLine(gateResult.Passed ? "GATE CHECK: PASSED" : "GATE CHECK: FAILED");
                    foreach (var v in gateResult.Violations)
                        Console.WriteLine($"  - {v}");
                }

                if (combinedResult.IsValid && (gateResult?.Passed ?? true))
                    Console.WriteLine("Validation: PASSED");
                else
                    Console.WriteLine("Validation: FAILED");
            }

            if (!combinedResult.IsValid || gateResult is { Passed: false })
                Environment.ExitCode = 1;
        });

        return cmd;
    }
}
