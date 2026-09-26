# CodePilot AI

## 🚀 Autonomous Code Analysis & Repair Agent

CodePilot AI is an AI-powered developer assistant that analyzes GitHub repositories, identifies code issues, explains them, and uses IBM Bob to assist with automatically applying and verifying fixes.

## 💡 Problem

Understanding and maintaining existing codebases can be difficult, especially when repositories contain many files and potential code-quality issues. Developers often need to manually identify problems, understand their context, implement fixes, and verify the results.

## 🎯 Solution

CodePilot AI provides an interactive workflow:

**Detect → Explain → Fix → Review → Verify**

Users can provide a public GitHub repository and analyze its codebase for potential issues. Each issue can be reviewed with its file location, severity, and explanation. IBM Bob can then be used to analyze the issue context, modify the relevant source file, and verify the applied fix.

## ✨ Features

- 🔍 GitHub repository analysis
- 🐛 Automatic code issue detection
- 📊 Issue categorization and severity
- 🤖 IBM Bob-assisted code fixing
- 🔧 Automated fix workflow
- 📝 Fix and change summaries
- 🔎 Code change review
- ✅ Fix verification
- 🌐 Web-based developer interface

## 🏗️ Project Structure

```text
copilot-ai/
├── frontend/
├── backend/
├── demo_repo/
├── .bob/
├── .vscode/
├── AGENTS.md
└── package-lock.json
