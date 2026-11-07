from typing import Any, Literal
from pydantic import BaseModel, EmailStr, Field, ConfigDict, model_validator
from app.config import MIN_PASSWORD_LENGTH

class RegisterIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    mobile: str = Field(min_length=7, max_length=30)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)
    confirm_password: str | None = Field(default=None, min_length=MIN_PASSWORD_LENGTH, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self):
        if self.confirm_password is not None and self.password != self.confirm_password:
            raise ValueError("Password and confirm password do not match.")
        digits = "".join(ch for ch in self.mobile if ch.isdigit())
        if len(digits) < 10 or len(digits) > 15:
            raise ValueError("Enter a valid mobile number.")
        return self

class OTPIn(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")

class ResendOTPIn(BaseModel):
    email: EmailStr

class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

class PasswordResetRequestIn(BaseModel):
    email: EmailStr
    account_type: Literal["CUSTOMER", "REVIEWER", "BANK_ADMIN"]

class PasswordResetCompleteIn(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)
    confirm_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("Password and confirm password do not match.")
        return self

class CustomerOut(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    mobile: str
    is_verified: bool
    model_config = ConfigDict(from_attributes=True)

class ProfileUpdateIn(BaseModel):
    mobile: str = Field(min_length=7, max_length=30)
    @model_validator(mode="after")
    def valid_mobile(self):
        digits = "".join(ch for ch in self.mobile if ch.isdigit())
        if not 10 <= len(digits) <= 15:
            raise ValueError("Enter a valid mobile number.")
        return self

class ApplicationIn(BaseModel):
    lender_name: str = Field(default="", max_length=160)
    product_name: str = Field(default="", max_length=160)
    property_address: str = Field(default="", max_length=4000)
    property_value: float = Field(default=0, ge=0, le=10**13)
    requested_loan: float = Field(default=0, ge=0, le=10**13)
    annual_income: float = Field(default=0, ge=0, le=10**12)
    monthly_debt: float = Field(default=0, ge=0, le=10**10)
    interest_rate: float = Field(default=8.5, ge=0, le=40)
    tenure_years: int = Field(default=20, ge=1, le=40)
    customer_notes: str = Field(default="", max_length=5000)
    details: dict[str, Any] = Field(default_factory=dict)
    consents: dict[str, bool] = Field(default_factory=dict)

class ApplicationSubmitIn(BaseModel):
    confirm: bool = True

class AITestIn(BaseModel):
    text: str = Field(min_length=1, max_length=24000)
    scenario: str = Field(default="document_review", max_length=80)

class DocumentTextEditIn(BaseModel):
    edited_text: str = Field(max_length=1000000)

class DocumentFieldsEditIn(BaseModel):
    corrected_fields: dict[str, Any] = Field(max_length=100)
    reason: str = Field(default="", max_length=1000)

class NotificationReadIn(BaseModel):
    read: bool = True

class IncomeYearIn(BaseModel):
    year: str = Field(min_length=2, max_length=20)
    itr_total_income: float | None = Field(default=None, ge=0, le=10**12)
    salary_income: float | None = Field(default=None, ge=0, le=10**12)
    bank_credits: float | None = Field(default=None, ge=0, le=10**12)

class ScenarioIn(BaseModel):
    valuation_amount: float | None = Field(default=None, ge=0, le=10**13)
    purchase_price: float | None = Field(default=None, ge=0, le=10**13)
    max_ltv_percent: float | None = Field(default=None, gt=0, le=100)
    tolerance_percent: float | None = Field(default=None, gt=0, le=100)
    income_years: list[IncomeYearIn] = Field(default_factory=list, max_length=10)
    terms_text: str | None = Field(default=None, max_length=200000)
