namespace MiniMaxAIDocx.Core.Validation;

public class ValidationResult
{
    public bool IsValid => Errors.Count == 0;
    public List<ValidationError> Errors { get; set; } = new();
    public List<ValidationError> Warnings { get; set; } = new();

    public void Merge(ValidationResult other)
    {
        Errors.AddRange(other.Errors);
        Warnings.AddRange(other.Warnings);
    }
}

public class ValidationError
{
    public int LineNumber { get; set; }
    public int LinePosition { get; set; }
    public string Element { get; set; } = "";
    public string Message { get; set; } = "";
    public string Severity { get; set; } = "Error";
}
