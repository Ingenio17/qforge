# Contributing to QForge

Thank you for your interest in contributing to QForge! This document provides guidelines for contributing to the project.

## Code of Conduct

Please be respectful and constructive in all interactions with the community.

## How to Contribute

### Reporting Bugs

If you find a bug, please open an issue on GitHub with:
- A clear, descriptive title
- Steps to reproduce the issue
- Expected behavior vs actual behavior
- Your environment (OS, Python version, QForge version)
- Any relevant code snippets or error messages

### Suggesting Enhancements

We welcome feature requests and enhancement suggestions! Please open an issue with:
- A clear description of the feature
- The use case and why it would be valuable
- Any relevant examples or mockups

### Pull Requests

1. **Fork the repository** and create a new branch for your feature or bugfix
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Install development dependencies**
   ```bash
   # For bash/zsh shells:
   pip install -e ".[dev]"
   
   # For Windows cmd (without quotes):
   pip install -e .[dev]
   ```

3. **Make your changes** following our coding standards
   - Write clear, concise code with appropriate comments
   - Follow the existing code style
   - Add tests for new functionality
   - Update documentation as needed

4. **Run tests** to ensure everything works
   ```bash
   pytest
   ```

5. **Format your code** with our tools
   ```bash
   black qforge tests
   ruff check qforge tests --fix
   ```

6. **Commit your changes** with clear, descriptive commit messages
   ```bash
   git commit -m "Add feature: description of changes"
   ```

7. **Push to your fork** and submit a pull request
   ```bash
   git push origin feature/your-feature-name
   ```

## Development Guidelines

### Code Style

- We use [Black](https://black.readthedocs.io/) for code formatting (line length: 100)
- We use [Ruff](https://docs.astral.sh/ruff/) for linting
- Type hints are encouraged but not required
- Follow PEP 8 conventions

### Testing

- Write tests for all new functionality
- Maintain or improve code coverage
- Use pytest fixtures for common test setup
- Mark slow or integration tests appropriately:
  ```python
  @pytest.mark.slow
  @pytest.mark.integration
  ```

### Documentation

- Update the README.md if you add new features
- Add docstrings to all public functions and classes
- Update relevant documentation in the `docs/` directory
- Include examples for new functionality

### Commit Messages

- Use clear, descriptive commit messages
- Start with a verb in the present tense (e.g., "Add", "Fix", "Update")
- Reference issue numbers when applicable (e.g., "Fix #123: Description")

## Project Structure

```
qforge/
├── qforge/           # Main package
│   ├── cli/          # Command-line interface
│   ├── core/         # Core engines (qubit, gate, circuit, hardware)
│   ├── comparison/   # Comparison and analysis tools
│   ├── config/       # Configuration and defaults
│   ├── plugins/      # Plugin system
│   └── utils/        # Utility functions
├── tests/            # Test suite
├── examples/         # Example scripts
├── docs/             # Documentation
└── pyproject.toml    # Project configuration
```

## Areas for Contribution

We especially welcome contributions in these areas:

### High Priority
- **Gate Physics**: Implementing quantum gate dynamics with QuTiP
- **Circuit Simulation**: Multi-qubit circuit simulation with Qiskit
- **Hardware Design**: Chip layout design integration
- **Additional Qubit Types**: Support for more qubit architectures

### Medium Priority
- **Documentation**: Tutorials, guides, and API documentation
- **Testing**: Expanding test coverage
- **Performance**: Optimization of computational routines
- **Examples**: More workflow examples and use cases

### Good First Issues
- Bug fixes
- Documentation improvements
- Adding type hints
- Writing tests for existing functionality

## Getting Help

If you need help with your contribution:
- Open a discussion on GitHub
- Comment on the relevant issue
- Reach out to the maintainers

## License

By contributing to QForge, you agree that your contributions will be licensed under the Apache License 2.0.

## Recognition

All contributors will be recognized in our release notes and documentation. Thank you for making QForge better!
